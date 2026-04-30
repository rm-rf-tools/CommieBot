"""aipac.py"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import io
import textwrap
from PIL import Image, ImageDraw, ImageFont

# Attempt to load background removal libraries
def remove_background(image_bytes: bytes) -> bytes:
    try:
        # Fallback to the industry standard (rembg)
        from rembg import remove
        return remove(image_bytes)
    except ImportError as err:
        print("rembg failed", err)
        
    try:
        # Try the user's withoutbg library first
        import withoutbg
        return withoutbg.remove(image_bytes)
    except Exception:
        raise RuntimeError("Background removal failed. Please find alt")
 


AIPAC_DIR = "./data/aipac"
TEMPLATE_PATH = "./static/images/aipac.png"
FONT_PATH = "./static/fonts/BebasNeueBold-7B9LE.ttf"

class AipacCog(commands.GroupCog, name="aipac"):
    def __init__(self, bot):
        self.bot = bot
        # We store the cut-out PNGs locally
        os.makedirs(AIPAC_DIR, exist_ok=True)

    # --- AUTOCOMPLETE FUNCTION ---
    # This fetches names directly from the saved image files for /aipac gen and /aipac delete
    async def name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not os.path.exists(AIPAC_DIR):
            return []
        files = os.listdir(AIPAC_DIR)
        names = [f[:-4].replace("_", " ").title() for f in files if f.endswith(".png")]
        return [
            app_commands.Choice(name=n, value=n) 
            for n in names if current.lower() in n.lower()
        ][:25]

    # ==========================================
    #               COMMANDS
    # ==========================================

    @app_commands.command(name="add", description="Remove background from a photo and save them to the AIPAC roster.")
    @app_commands.describe(name="Name of the person", photo="The photo to cut out")
    async def aipac_add(self, interaction: discord.Interaction, name: str, photo: discord.Attachment):
        if not photo.content_type or not photo.content_type.startswith('image/'):
            return await interaction.response.send_message("❌ Please upload a valid image file.", ephemeral=True)

        await interaction.response.defer()

        try:
            # 1. Download image and remove background
            input_bytes = await photo.read()
            bg_removed_bytes = remove_background(input_bytes)
            
            # 2. Open with PIL and crop out transparent whitespace
            img = Image.open(io.BytesIO(bg_removed_bytes)).convert("RGBA")
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
                
            # 3. Resize constraints: Max width 575, Max height 830 (1080 - 250)
            max_w, max_h = 575, 830
            ratio = min(max_w / img.width, max_h / img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # 4. Save to disk
            safe_name = name.strip().replace(" ", "_").lower()
            save_path = os.path.join(AIPAC_DIR, f"{safe_name}.png")
            img.save(save_path, "PNG")
            
            await interaction.followup.send(f"✅ Successfully added and cut out **{name.title()}**!")
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to process the image: {e}")

    @app_commands.command(name="gen", description="Generate an AIPAC graphic using a saved person.")
    @app_commands.describe(name="Select a previously added person")
    @app_commands.autocomplete(name=name_autocomplete)
    async def aipac_gen(self, interaction: discord.Interaction, name: str):
        safe_name = name.strip().replace(" ", "_").lower()
        person_path = os.path.join(AIPAC_DIR, f"{safe_name}.png")
        
        if not os.path.exists(person_path):
            return await interaction.response.send_message(f"❌ Could not find **{name.title()}**. Have you added them with `/aipac add` yet?", ephemeral=True)

        await interaction.response.defer()

        try:
            # 1. Load background template and person PNG
            template = Image.open(TEMPLATE_PATH).convert("RGBA")
            person = Image.open(person_path).convert("RGBA")
            
            # 2. Paste person into position
            # They stay within X: 0-575 and anchor to the bottom (Y=1080)
            paste_x = (575 - person.width) // 2  # Centered in the 0-575 space
            paste_y = 1080 - person.height       # Anchored to the bottom 
            
            template.paste(person, (paste_x, paste_y), person)
            
            # 3. Draw Text in the specific Bounding Box
            # Top-Left: (597, 407) | Bottom-Right: (890, 522)
            draw = ImageDraw.Draw(template)
            box_w = 890 - 597
            box_h = 522 - 407
            
            # Helper logic to dynamic-scale text to fit the box beautifully
            best_size = 12
            best_text = name.title()
            
            for size in range(95, 10, -2):
                try:
                    font = ImageFont.truetype(FONT_PATH, size)
                except IOError:
                    font = ImageFont.load_default()
                    
                # Wrap text if it's too long
                chars_per_line = int(box_w / (size * 0.5))
                wrapped = textwrap.fill(name.upper(), width=chars_per_line if chars_per_line > 0 else 1)
                
                bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="left")
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                
                if text_w <= box_w and text_h <= box_h:
                    best_size = size
                    best_text = wrapped
                    break
            
            try:
                final_font = ImageFont.truetype(FONT_PATH, best_size)
            except IOError:
                final_font = ImageFont.load_default()
            
            # Draw the text anchored strictly to the top-left of your specified box
            draw.multiline_text((597, 407), best_text, font=final_font, fill=(255, 255, 255, 255), align="left")

            # 4. Save and Export
            final_img = template.convert("RGB")
            buffer = io.BytesIO()
            final_img.save(buffer, format="JPEG", quality=95)
            buffer.seek(0)
            
            file = discord.File(fp=buffer, filename=f"aipac_{safe_name}.jpg")
            await interaction.followup.send(file=file)

        except Exception as e:
            await interaction.followup.send(f"❌ Failed to generate graphic: {e}")

    @app_commands.command(name="delete", description="Delete a saved person from the AIPAC roster.")
    @app_commands.describe(name="Select the person to remove")
    @app_commands.autocomplete(name=name_autocomplete)
    async def aipac_delete(self, interaction: discord.Interaction, name: str):
        safe_name = name.strip().replace(" ", "_").lower()
        person_path = os.path.join(AIPAC_DIR, f"{safe_name}.png")
        
        if not os.path.exists(person_path):
            return await interaction.response.send_message(f"❌ Could not find **{name.title()}** in the roster.", ephemeral=True)

        try:
            os.remove(person_path)
            await interaction.response.send_message(f"🗑️ Successfully removed **{name.title()}** from the AIPAC roster.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to delete image: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AipacCog(bot))