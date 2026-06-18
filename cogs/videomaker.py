"""
filename: videomaker.py
description: Generates video memes by overlaying dynamic text onto predefined video templates using MoviePy.
Views:
    - None
Commands:
    - /video <template> <text>: Create a video meme from a selection of templates. (User)
"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import textwrap
import asyncio
from functools import partial
import numpy as np
from PIL import Image, ImageDraw, ImageFont


from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip

FONT_DIR = "./static/fonts"
VIDEO_DIR = "./data/videos"
TEMP_DIR = "./data/temp"


os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


#        HARDCODED VIDEO TEMPLATES


# box_x / box_y is the top left corner of your white box.
# box_w / box_h is the size of the white box.

TEMPLATES = {
    "snapchat_meme": {
        "file": "snapchat_template.mp4",
        "box_x": 50,           # Pixels from the left
        "box_y": 100,          # Pixels from the top
        "box_w": 620,          # Width of the white box
        "box_h": 150,          # Height of the white box
        "font_file": "BebasNeueRegular-X34j2.otf", 
        "font_size": 45,
        "text_color": (0, 0, 0, 255), # Black text
        "max_chars_per_line": 25
    },
    "breaking_news": {
        "file": "news_template.mp4",
        "box_x": 100,
        "box_y": 800,
        "box_w": 880,
        "box_h": 200,
        "font_file": "MouldyCheeseRegular-WyMWG.ttf",
        "font_size": 60,
        "text_color": (255, 255, 255, 255), # White text
        "max_chars_per_line": 35
    }
}


#        VIDEO PROCESSING LOGIC


def render_video_sync(template_id: str, text: str, output_path: str):
    """
    This function runs synchronously to process the video.
    We run this in an executor so it doesn't freeze the Discord bot!
    """
    config = TEMPLATES[template_id]
    video_path = os.path.join(VIDEO_DIR, config["file"])
    
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Template video file {config['file']} not found in {VIDEO_DIR}.")

    # 1. Create a Transparent Image for the Text Box using PIL
    img = Image.new('RGBA', (config["box_w"], config["box_h"]), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    font_path = os.path.join(FONT_DIR, config["font_file"])
    try:
        font = ImageFont.truetype(font_path, size=config["font_size"])
    except IOError:
        font = ImageFont.load_default()

    # Wrap the text so it fits the box
    wrapped_text = textwrap.fill(text, width=config["max_chars_per_line"])
    
    # Draw text in the center of our transparent box
    draw.multiline_text(
        (config["box_w"]/2, config["box_h"]/2), 
        wrapped_text, 
        font=font, 
        fill=config["text_color"], 
        anchor="mm", # Middle Center
        align="center"
    )

    
    img_array = np.array(img)

    
    video = VideoFileClip(video_path)
    
    
    text_clip = (ImageClip(img_array)
                 .set_duration(video.duration)
                 .set_position((config["box_x"], config["box_y"])))

    
    final_video = CompositeVideoClip([video, text_clip])

    
    
    final_video.write_videofile(
        output_path, 
        codec="libx264", 
        audio_codec="aac", 
        fps=video.fps,
        preset="ultrafast", 
        logger=None 
    )
    
    
    video.close()
    text_clip.close()
    final_video.close()


#               DISCORD COG


class VideoMaker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="video", description="Add your text to a video template!")
    @app_commands.describe(template="Which video template to use", text="The text to put in the video")
    @app_commands.choices(template=[
        app_commands.Choice(name=key.replace("_", " ").title(), value=key) for key in TEMPLATES.keys()
    ])
    async def videomaker(self, interaction: discord.Interaction, template: app_commands.Choice[str], text: str):
        
        await interaction.response.defer(thinking=True)
        
        template_id = template.value
        output_filename = f"vid_{interaction.id}.mp4"
        output_path = os.path.join(TEMP_DIR, output_filename)

        try:
            
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, 
                partial(render_video_sync, template_id, text, output_path)
            )

            
            file = discord.File(output_path, filename="meme.mp4")
            await interaction.followup.send(file=file)

        except Exception as e:
            await interaction.followup.send(f"❌ Failed to generate video: {e}")
            
        finally:
            
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass

async def setup(bot):
    await bot.add_cog(VideoMaker(bot))
