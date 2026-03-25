import discord
from discord import app_commands
from discord.ext import commands
import os
import io
import textwrap
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
from database import DatabaseController

# ==========================================
#        CONFIGURATION & SETTINGS
# ==========================================

# Directories
QUOTE_DIR = "./data/quotes"
FONT_DIR = "./static/fonts"

# Image Processing
IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1350
IMAGE_DARKEN_FACTOR = 0.5  # 0.0 is black, 1.0 is original brightness
JPEG_QUALITY = 90

# Fonts
QUOTE_FONT_FILE = "MouldyCheeseRegular-WyMWG.ttf"
QUOTE_FONT_SIZE = 75

AUTHOR_FONT_FILE = "MangabeyRegular-rgqVO.otf"
AUTHOR_FONT_SIZE = 86

# Text Layout
MAX_CHAR_COUNT = 25
LINE_HEIGHT = 55           # Multiplier for calculating author placement
AUTHOR_OFFSET_BASE = 40    # Extra pixels added between the quote and the author

# Colors & Effects (RGBA format: Red, Green, Blue, Alpha/Transparency)
TEXT_COLOR = (255, 255, 255, 255)  # Solid White
SHADOW_COLOR = (0, 0, 0, 128)      # Semi-transparent Black
SHADOW_OFFSET_X = 5
SHADOW_OFFSET_Y = 5

# ==========================================

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
        """Crops, resizes, and darkens the image based on config settings."""
        target_size = (IMAGE_WIDTH, IMAGE_HEIGHT)
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

        # Resize to exact standard portrait size
        if img.size != target_size:
            img = img.resize(target_size, Image.Resampling.LANCZOS)

        # Darken the image
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(IMAGE_DARKEN_FACTOR)

        # Save the file
        file_path = os.path.join(QUOTE_DIR, f"{filename}.jpg")
        img.save(file_path, "JPEG", quality=JPEG_QUALITY)
        return file_path

    def generate_quote_image(self, template_path: str, quote_text: str, author_text: str) -> io.BytesIO:
        """Draws the text onto the pre-processed template image."""
        img = Image.open(template_path).convert("RGBA")
        
        # Load EXACT fonts from your static folder
        try:
            quote_font = ImageFont.truetype(os.path.join(FONT_DIR, QUOTE_FONT_FILE), size=QUOTE_FONT_SIZE)
            author_font = ImageFont.truetype(os.path.join(FONT_DIR, AUTHOR_FONT_FILE), size=AUTHOR_FONT_SIZE)
        except IOError:
            quote_font = ImageFont.load_default()
            author_font = ImageFont.load_default()
            print(f"WARNING: Could not find fonts in {FONT_DIR}. Using default.")

        draw = ImageDraw.Draw(im=img)

        # Wrap text
        new_text = textwrap.fill(text=quote_text, width=MAX_CHAR_COUNT)
        
        # FIX FONT WITH SPACES (Critical for certain fonts' padding)
        new_text = new_text.replace(" ", "  ")
        
        x_text = img.size[0] / 2
        y_text = img.size[1] / 2
        position = (x_text, y_text)

        # Draw the shadow text
        shadow_position = (x_text + SHADOW_OFFSET_X, y_text + SHADOW_OFFSET_Y)
        draw.text(shadow_position, new_text, font=quote_font, fill=SHADOW_COLOR, anchor='mm', align='center')

        # Add main text to the image
        draw.text(position, text=new_text, font=quote_font, fill=TEXT_COLOR, anchor='mm', align='center')

        if author_text:
            # Dynamic height calculation
            num_of_lines = new_text.count("\n") + 1
            text_height = (LINE_HEIGHT * num_of_lines) + AUTHOR_OFFSET_BASE
            
            author_position = (position[0], position[1] + text_height)
            
            # Draw author exactly as the name (no hyphens)
            draw.text(author_position, text=author_text, font=author_font, fill=TEXT_COLOR, anchor='mm', align='center')

        # Convert back to RGB to save as JPEG
        final_img = img.convert("RGB")
        buffer = io.BytesIO()
        final_img.save(buffer, format="JPEG")
        buffer.seek(0)
        return buffer

    # --- AUTOCOMPLETE FUNCTION ---
    async def template_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Fetches templates from the database and filters them as the user types."""
        templates = await DatabaseController.get_all_quote_templates()
        if not templates:
            return []

        choices =[]
        for t in templates:
            db_name = t[0]  # e.g., 'karl_marx'
            pretty_name = display_name(db_name)  # e.g., 'Karl Marx'
            
            # Match user input against both the display name and DB name
            if current.lower() in pretty_name.lower() or current.lower() in db_name:
                # The user sees the pretty_name, but the bot receives the db_name as the value
                choices.append(app_commands.Choice(name=pretty_name, value=db_name))

        # Discord limits autocomplete options to 25 items maximum
        return choices[:25]

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
    @app_commands.describe(name="The template name (start typing to search)", quote="The quote text")
    @app_commands.autocomplete(name=template_autocomplete)  # <--- LINKED AUTOCOMPLETE HERE
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