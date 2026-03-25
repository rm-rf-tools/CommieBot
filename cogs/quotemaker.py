import discord
from discord import app_commands
from discord.ext import commands
import os
import io
import textwrap
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
from database import DatabaseController

QUOTE_DIR = "./data/quotes"
FONT_DIR = "./static/fonts" # Updated to match your exact directory tree

# Ensure directory for quotes exists
os.makedirs(QUOTE_DIR, exist_ok=True)

def clean_name(name: str) -> str:
    """Converts 'Karl Marx' or 'karl_marx' to 'karl_marx' for DB/Filesystem"""
    return name.lower().replace(" ", "_").strip()

def display_name(name: str) -> str:
    """Converts 'karl_marx' back to 'Karl Marx' for Discord responses and Image Author Text"""
    return name.replace("_", " ").title()

class QuoteMaker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def process_and_save_image(self, image_bytes: bytes, filename: str) -> str:
        """Crops to 1080x1350, resizes, and darkens the image."""
        target_size = (1080, 1350)
        desired_ratio = target_size[0] / target_size[1]

        # Open image from bytes
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = img.size
        ratio = width / height

        # Calculate new dimensions for cropping
        if ratio > desired_ratio:
            new_width = round(height * desired_ratio)
            new_height = height
        else:
            new_width = width
            new_height = round(width / desired_ratio)

        # Center crop
        left = (width - new_width) / 2
        top = (height - new_height) / 2
        right = left + new_width
        bottom = top + new_height
        img = img.crop((left, top, right, bottom))

        # Resize to exact standard Instagram Portrait size
        if img.size != target_size:
            img = img.resize(target_size, Image.Resampling.LANCZOS)

        # Darken the image by 50%
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.5)

        # Save the file
        file_path = os.path.join(QUOTE_DIR, f"{filename}.jpg")
        img.save(file_path, "JPEG", quality=90)
        return file_path

    def generate_quote_image(self, template_path: str, quote_text: str, author_text: str) -> io.BytesIO:
        """Draws the text onto the pre-processed template image exactly like the original script."""
        img = Image.open(template_path).convert("RGBA")
        
        # Load EXACT fonts from your static folder
        try:
            quote_font = ImageFont.truetype(f"{FONT_DIR}/MouldyCheeseRegular-WyMWG.ttf", size=75)
            author_font = ImageFont.truetype(f"{FONT_DIR}/MangabeyRegular-rgqVO.otf", size=45)
        except IOError:
            quote_font = ImageFont.load_default()
            author_font = ImageFont.load_default()
            print("WARNING: Could not find fonts in static/fonts/. Using default.")

        draw = ImageDraw.Draw(im=img)

        # Wrap text exactly like example program
        max_char_count = 25
        new_text = textwrap.fill(text=quote_text, width=max_char_count)
        
        # FIX FONT WITH SPACES (Critical for MouldyCheese font padding)
        new_text = new_text.replace(" ", "  ")
        
        x_text = img.size[0] / 2
        y_text = img.size[1] / 2
        position = (x_text, y_text)

        # Draw the shadow text
        shadow_color = (0, 0, 0, 128)
        shadow_position = (x_text+5, y_text+5)
        draw.text(shadow_position, new_text, font=quote_font, fill=shadow_color, anchor='mm', align='center')

        # Add main text to the image
        draw.text(position, text=new_text, font=quote_font, fill=(255, 255, 255, 255), anchor='mm', align='center')

        if author_text:
            # Exact line height and offset math from your original program
            num_of_lines = new_text.count("\n") + 1
            line_height = 55     
            text_height = line_height * num_of_lines + 40
            
            author_position = (position[0], position[1] + text_height)
            # Draw author exactly as the name (no hyphens)
            draw.text(author_position, text=author_text, font=author_font, fill=(255, 255, 255, 255), anchor='mm', align='center')

        # Convert back to RGB to save as JPEG
        final_img = img.convert("RGB")
        buffer = io.BytesIO()
        final_img.save(buffer, format="JPEG")
        buffer.seek(0)
        return buffer

    @app_commands.command(name="quoteadd", description="Add a new quote background template.")
    @app_commands.describe(name="Name for this template (e.g. Karl Marx)", photo="The background image to crop and save")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def quoteadd(self, interaction: discord.Interaction, name: str, photo: discord.Attachment):
        if not photo.content_type or not photo.content_type.startswith('image/'):
            return await interaction.response.send_message("❌ Please upload a valid image file.", ephemeral=True)

        await interaction.response.defer()

        try:
            image_bytes = await photo.read()
            
            # Format names: clean for DB, display for Discord
            db_name = clean_name(name)
            pretty_name = display_name(db_name)
            
            # Process and save the image
            file_path = self.process_and_save_image(image_bytes, db_name)
            
            # Add to database
            await DatabaseController.add_quote_template(db_name, file_path)
            
            await interaction.followup.send(f"✅ Quote template **{pretty_name}** added successfully! Use `/quotegen \"{pretty_name}\"` to use it.")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to process the image: {e}")

    @app_commands.command(name="quotelist", description="List all available quote background templates.")
    async def quotelist(self, interaction: discord.Interaction):
        templates = await DatabaseController.get_all_quote_templates()
        if not templates:
            return await interaction.response.send_message("There are currently no templates. Admins can add some using `/quoteadd`.", ephemeral=True)

        # Format DB names ('karl_marx') to Display names ('Karl Marx') for the list
        template_list = "\n".join([f"• **{display_name(t[0])}**" for t in templates])
        embed = discord.Embed(title="Available Quote Templates", description=template_list, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quotegen", description="Generate a quote image.")
    @app_commands.describe(name="The template name (use /quotelist)", quote="The quote text")
    async def quotegen(self, interaction: discord.Interaction, name: str, quote: str):
        # Allow user to type "Karl Marx", "karl marx", or "karl_marx"
        db_name = clean_name(name)
        pretty_name = display_name(db_name)
        
        template_path = await DatabaseController.get_quote_template(db_name)
        
        if not template_path or not os.path.exists(template_path):
            return await interaction.response.send_message(f"❌ Template **{pretty_name}** not found. Check `/quotelist`.", ephemeral=True)

        await interaction.response.defer()

        try:
            # Passes 'Karl Marx' automatically as the author text
            image_buffer = self.generate_quote_image(template_path, quote, pretty_name)
            file = discord.File(fp=image_buffer, filename="quote.jpg")
            await interaction.followup.send(file=file)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to generate quote: {e}")

async def setup(bot):
    await bot.add_cog(QuoteMaker(bot))