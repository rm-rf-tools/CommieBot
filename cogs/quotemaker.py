import discord
from discord import app_commands
from discord.ext import commands
import os
import io
import textwrap
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
from database import DatabaseController

# ==========================================
#        GLOBAL CONFIGURATION
# ==========================================

QUOTE_DIR = "./data/quotes"
FONT_DIR = "./static/fonts"

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1350
IMAGE_DARKEN_FACTOR = 0.5  # Applied when saving the background to the DB
JPEG_QUALITY = 90

QUOTE_FONT_FILE = "MouldyCheeseRegular-WyMWG.ttf"
QUOTE_FONT_SIZE = 75

AUTHOR_FONT_FILE = "MangabeyRegular-rgqVO.otf"
AUTHOR_FONT_SIZE = 85

# ==========================================
#        LAYOUT 1: CLASSIC (CENTERED)
# ==========================================
CLASSIC_MAX_CHAR = 25
CLASSIC_TEXT_COLOR = (255, 255, 255, 255)  # White
CLASSIC_SHADOW_COLOR = (0, 0, 0, 128)      # Semi-transparent Black
CLASSIC_SHADOW_OFFSET_X = 5
CLASSIC_SHADOW_OFFSET_Y = 5
CLASSIC_AUTHOR_OFFSET_BASE = 100            # Space between quote and author

# ==========================================
#        LAYOUT 2: MODERN (LEFT FADE)
# ==========================================
FADE_TEXT_COLOR = (0, 0, 0, 255)           # Black text
FADE_LINE_COLOR = (0, 0, 0, 255)           # Black vertical line
FADE_LINE_WIDTH = 8                        # Thickness of vertical line
FADE_SOLID_WHITE_PCT = 0.12                # Left 45% is solid white (Increased for opacity)
FADE_START_ALPHA = 200
FADE_GRADIENT_END_PCT = 1.0                # Fades out to 0% at the very right edge
FADE_MARGIN_LEFT = 100                     # Distance from the left edge
FADE_TEXT_PADDING = 50                     # Space between vertical line and text
FADE_AUTHOR_OFFSET = 60                    # Space between quote and author
FADE_LINE_SPACING = 30   
# Dynamic Scaling Settings
FADE_AUTHOR_FONT_SIZE = 85                 # HUGE author font
FADE_QUOTE_START_SIZE = 85                # Maximum quote size it will try
FADE_QUOTE_MIN_SIZE = 40                   # Minimum quote size it will shrink to
FADE_MAX_TEXT_WIDTH_PCT = 0.55             # Quote max width (55% of image width)
FADE_MAX_TEXT_HEIGHT_PCT = 0.70            # Max height the quote+author can take up

# ==========================================
#               IMAGE LAYOUTS
# ==========================================

class ClassicLayout:
    """The original centered layout with white text and drop shadows."""
    
    @staticmethod
    def generate(template_path: str, quote_text: str, author_text: str) -> io.BytesIO:
        quote_text=f'"{quote_text}"'
        # FIX: Check if template_path is a string path or a PIL Image object
        img = (template_path if not isinstance(template_path, str) else Image.open(template_path)).convert("RGBA")
        
        try:
            quote_font = ImageFont.truetype(os.path.join(FONT_DIR, QUOTE_FONT_FILE), size=QUOTE_FONT_SIZE)
            author_font = ImageFont.truetype(os.path.join(FONT_DIR, AUTHOR_FONT_FILE), size=AUTHOR_FONT_SIZE)
        except IOError:
            quote_font = ImageFont.load_default()
            author_font = ImageFont.load_default()

        draw = ImageDraw.Draw(im=img)

        # Wrap text
        new_text = textwrap.fill(text=quote_text, width=CLASSIC_MAX_CHAR)
        new_text = new_text.replace(" ", "  ")
        
        x_text, y_text = img.size[0] / 2, (img.size[1] / 3) * 2
        position = (x_text, y_text)

        # Draw shadow & main text
        shadow_position = (x_text + CLASSIC_SHADOW_OFFSET_X, y_text + CLASSIC_SHADOW_OFFSET_Y)
        draw.multiline_text(shadow_position, new_text, font=quote_font, fill=CLASSIC_SHADOW_COLOR, anchor='mm', align='center')
        draw.multiline_text(position, text=new_text, font=quote_font, fill=CLASSIC_TEXT_COLOR, anchor='mm', align='center')

        if author_text:
            bbox = draw.multiline_textbbox(position, new_text, font=quote_font, anchor='mm', align='center')
            text_height = bbox[3] - bbox[1]
            author_position = (position[0], position[1] + (text_height / 2) + CLASSIC_AUTHOR_OFFSET_BASE)
            draw.text(author_position, text=author_text, font=author_font, fill=CLASSIC_TEXT_COLOR, anchor='mm', align='center')

        # Export
        return export_image(img)

class FadeLayout:
    """The modern layout: B&W Image, dynamic scaling black text, left-aligned."""
    
    @staticmethod
    def generate(template_path: str, quote_text: str, author_text: str) -> io.BytesIO:
        # FIX: Check if template_path is a string path or a PIL Image object
        img = (template_path if not isinstance(template_path, str) else Image.open(template_path)).convert("L").convert("RGBA")
        width, height = img.size

        # 1. Apply the Custom White Gradient Mask
        white_overlay = Image.new('RGBA', (width, height), (255, 255, 255, 255))
        mask = Image.new('L', (width, height))
        draw_mask = ImageDraw.Draw(mask)

        fade_start = int(width * FADE_SOLID_WHITE_PCT)
        fade_end = int(width * FADE_GRADIENT_END_PCT)
        fade_width = fade_end - fade_start

        for x in range(width):
            if x <= fade_start:
                alpha = FADE_START_ALPHA  # Solid White
            elif x < fade_end:
                # Easing curve: keeps the white more opaque for longer before dropping off
                progress = (x - fade_start) / fade_width
                alpha = int(FADE_START_ALPHA * ((1 - progress) ** 2.45))
            else:
                alpha = 0    # Transparent
            draw_mask.line((x, 0, x, height), fill=alpha)

        img.paste(white_overlay, (0, 0), mask)

        # 2. Setup Fonts
        quote_font_path = os.path.join(FONT_DIR, QUOTE_FONT_FILE)
        author_font_path = os.path.join(FONT_DIR, AUTHOR_FONT_FILE)
        
        try:
            author_font = ImageFont.truetype(author_font_path, size=FADE_AUTHOR_FONT_SIZE)
        except IOError:
            author_font = ImageFont.load_default()

        draw = ImageDraw.Draw(img)

        # 3. Dynamic Font Scaling Algorithm
        max_w = width * FADE_MAX_TEXT_WIDTH_PCT
        max_h = height * FADE_MAX_TEXT_HEIGHT_PCT
        
        wrapped_quote = quote_text
        quote_h = 0
        quote_font = ImageFont.load_default()

        # Step down font sizes until it fits the designated area
        for size in range(FADE_QUOTE_START_SIZE, FADE_QUOTE_MIN_SIZE - 1, -2):
            try:
                q_font = ImageFont.truetype(quote_font_path, size=size)
            except IOError:
                q_font = ImageFont.load_default()
                break # Default font cant be scaled

            # Dynamically wrap text based on exact pixel length of the font
            words = quote_text.split()
            lines = []
            current_line =[]
            
            for word in words:
                test_line = " ".join(current_line + [word])
                # Check if adding this word exceeds our max width
                if q_font.getlength(test_line) <= max_w:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)  # Word itself is wider than max width
                        current_line =[]
            
            if current_line:
                lines.append(" ".join(current_line))
                
            test_wrapped = "\n".join(lines).replace(" ", "  ") # Preserve padding quirk
            
            # Check total height of text block + author
            bbox = draw.multiline_textbbox((0, 0), test_wrapped, font=q_font, spacing=FADE_LINE_SPACING)
            q_h = bbox[3] - bbox[1]
            
            a_bbox = draw.textbbox((0, 0), author_text, font=author_font)
            a_h = a_bbox[3] - a_bbox[1]
            
            total_h = q_h + FADE_AUTHOR_OFFSET + a_h
            
            if total_h <= max_h:
                # We found the perfect size!
                quote_font = q_font
                wrapped_quote = test_wrapped
                quote_h = q_h
                break

        # 4. Calculate Final Alignment Coordinates
        a_bbox = draw.textbbox((0, 0), author_text, font=author_font)
        a_h = a_bbox[3] - a_bbox[1]
        final_total_h = quote_h + FADE_AUTHOR_OFFSET + a_h
        
        start_y = (height - final_total_h) // 2
        line_x = FADE_MARGIN_LEFT
        text_x = FADE_MARGIN_LEFT + FADE_TEXT_PADDING

        # 5. Draw Elements
        # Vertical Line
        draw.line([(line_x, start_y + 10), (line_x, start_y + quote_h - 10)], fill=FADE_LINE_COLOR, width=FADE_LINE_WIDTH)
        
        # Huge quote marks
        try:
            # Scale quote mark to be double the size of the dynamically selected font
            quote_mark_font = ImageFont.truetype(quote_font_path, size=quote_font.size * 2)
            draw.text((line_x, start_y - quote_font.size), "“", font=quote_mark_font, fill=FADE_TEXT_COLOR, anchor='lt')
        except: pass # Fallback skips quote mark

        # Quote Text
        draw.multiline_text((text_x, start_y), wrapped_quote, font=quote_font, fill=FADE_TEXT_COLOR, align='left', spacing=FADE_LINE_SPACING)
        # Author Text
        draw.text((text_x, start_y + quote_h + FADE_AUTHOR_OFFSET), author_text, font=author_font, fill=FADE_TEXT_COLOR, align='left')

        # Export
        return export_image(img)

def export_image(img: Image.Image) -> io.BytesIO:
    """Helper function to convert PIL Image to BytesIO for Discord."""
    final_img = img.convert("RGB")
    buffer = io.BytesIO()
    final_img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    buffer.seek(0)
    return buffer

# ==========================================
#             DISCORD BOT COG
# ==========================================

os.makedirs(QUOTE_DIR, exist_ok=True)

def clean_name(name: str) -> str:
    return name.lower().replace(" ", "_").strip()

def display_name(name: str) -> str:
    return name.replace("_", " ").title()

class QuoteMaker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def process_and_save_image(self, image_bytes: bytes, filename: str) -> str:
        """Crops, resizes, and darkens the uploaded image, then saves it to disk."""
        target_size = (IMAGE_WIDTH, IMAGE_HEIGHT)
        desired_ratio = target_size[0] / target_size[1]

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = img.size
        ratio = width / height

        # Center crop
        if ratio > desired_ratio:
            new_width = round(height * desired_ratio)
            new_height = height
        else:
            new_width = width
            new_height = round(width / desired_ratio)

        left = (width - new_width) / 2
        top = (height - new_height) / 2
        img = img.crop((left, top, left + new_width, top + new_height))

        # Resize & Darken
        if img.size != target_size:
            img = img.resize(target_size, Image.Resampling.LANCZOS)
            
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(IMAGE_DARKEN_FACTOR)

        # Save
        file_path = os.path.join(QUOTE_DIR, f"{filename}.jpg")
        img.save(file_path, "JPEG", quality=JPEG_QUALITY)
        return file_path
        
    def process_raw_image(self, image_bytes: bytes) -> Image.Image:
        """Processes bytes into the standard 1080x1350 template format."""
        target_size = (IMAGE_WIDTH, IMAGE_HEIGHT)
        desired_ratio = target_size[0] / target_size[1]
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        ratio = w / h

        if ratio > desired_ratio:
            nw, nh = round(h * desired_ratio), h
        else:
            nw, nh = w, round(w / desired_ratio)

        left, top = (w - nw) / 2, (h - nh) / 2
        img = img.crop((left, top, left + nw, top + nh))
        img = img.resize(target_size, Image.Resampling.LANCZOS)
        return ImageEnhance.Brightness(img).enhance(IMAGE_DARKEN_FACTOR)

    @app_commands.command(name="quoteuser", description="Generate a quote from a user's profile picture.")
    @app_commands.describe(user="The user to quote", quote="The text to quote", layout="Visual style")
    @app_commands.choices(layout=[
        app_commands.Choice(name="Classic (Centered)", value="classic"),
        app_commands.Choice(name="Modern (Left Fade)", value="fade")
    ])
    async def quoteuser(self, interaction: discord.Interaction, user: discord.Member, quote: str, layout: app_commands.Choice[str] = None):
        await interaction.response.defer()
        try:
            # Fetch high-res avatar
            avatar_bytes = await user.display_avatar.with_size(1024).read()
            # Process into a standard template image object
            processed_avatar = self.process_raw_image(avatar_bytes)
            
            selected_layout = layout.value if layout else "fade"
            author_name = user.display_name

            if selected_layout == "fade":
                image_buffer = FadeLayout.generate(processed_avatar, quote, author_name)
            else:
                image_buffer = ClassicLayout.generate(processed_avatar, quote, author_name)

            file = discord.File(fp=image_buffer, filename=f"quote_{user.id}.jpg")
            await interaction.followup.send(file=file)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to quote user: {e}")

    # --- AUTOCOMPLETE TEMPLATES ---
    async def template_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        templates = await DatabaseController.get_all_quote_templates()
        if not templates: return []
        
        choices = []
        for t in templates:
            db_name = t[0]
            pretty_name = display_name(db_name)
            if current.lower() in pretty_name.lower() or current.lower() in db_name:
                choices.append(app_commands.Choice(name=pretty_name, value=db_name))
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
            db_name = clean_name(name)
            
            file_path = self.process_and_save_image(image_bytes, db_name)
            await DatabaseController.add_quote_template(db_name, file_path)
            
            await interaction.followup.send(f"✅ Quote template **{display_name(db_name)}** added successfully!")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to process the image: {e}")

    @app_commands.command(name="quotelist", description="List all available quote background templates.")
    async def quotelist(self, interaction: discord.Interaction):
        templates = await DatabaseController.get_all_quote_templates()
        if not templates:
            return await interaction.response.send_message("There are currently no templates.", ephemeral=True)

        template_list = "\n".join([f"• **{display_name(t[0])}**" for t in templates])
        embed = discord.Embed(title="Available Quote Templates", description=template_list, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quotegen", description="Generate a quote image.")
    @app_commands.describe(
        name="The template name (start typing to search)", 
        quote="The quote text",
        layout="Choose the visual layout (Default: Classic Centered)"
    )
    @app_commands.autocomplete(name=template_autocomplete)
    @app_commands.choices(layout=[
        app_commands.Choice(name="Classic (Centered)", value="classic"),
        app_commands.Choice(name="Modern (Left Fade)", value="fade")
    ])
    async def quotegen(self, interaction: discord.Interaction, name: str, quote: str, layout: app_commands.Choice[str] = None):
        db_name = clean_name(name)
        pretty_name = display_name(db_name)
        template_path = await DatabaseController.get_quote_template(db_name)
        
        if not template_path or not os.path.exists(template_path):
            return await interaction.response.send_message(f"❌ Template **{pretty_name}** not found.", ephemeral=True)

        await interaction.response.defer()

        try:
            # Determine which layout class to use based on user selection
            selected_layout = layout.value if layout else "classic"
            
            if selected_layout == "fade":
                image_buffer = FadeLayout.generate(template_path, quote, pretty_name)
            else:
                image_buffer = ClassicLayout.generate(template_path, quote, pretty_name)

            file = discord.File(fp=image_buffer, filename=f"quote_{selected_layout}.jpg")
            await interaction.followup.send(file=file)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to generate quote: {e}")

    @app_commands.command(name="quotedelete", description="Remove a quote background template.")
    @app_commands.describe(name="The template to delete (start typing to search)")
    @app_commands.autocomplete(name=template_autocomplete) # Reuses your existing autocomplete
    @app_commands.checks.has_permissions(manage_messages=True)
    async def quotedelete(self, interaction: discord.Interaction, name: str):
        db_name = clean_name(name)
        pretty_name = display_name(db_name)
        
        # 1. Get the template path from the database
        template_path = await DatabaseController.get_quote_template(db_name)
        
        if not template_path:
            return await interaction.response.send_message(f"❌ Template **{pretty_name}** does not exist in the database.", ephemeral=True)

        await interaction.response.defer()

        try:
            # 2. Delete the physical file if it exists
            if os.path.exists(template_path):
                os.remove(template_path)
            
            # 3. Delete the record from the database
            # Note: Ensure your DatabaseController has a delete_quote_template method
            await DatabaseController.delete_quote_template(db_name)
            
            await interaction.followup.send(f"✅ Successfully deleted template: **{pretty_name}**")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to delete template: {e}")
async def setup(bot):
    await bot.add_cog(QuoteMaker(bot))