"""
filename: mock_reddit.py
description: Generates highly realistic mock Reddit posts using a Jinja2 template and headless Selenium.
Views:
    - None
Commands:
    - /reddit create <subreddit> <title> <image> [text] [upvotes] [comments]: Create a mock Reddit post and send it to the channel. (User)
"""

import os
import random
import tempfile
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from jinja2 import Template
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ==========================================
# 1. Text Corpus for Username Generation
# ==========================================
ADJECTIVES = [
    "Suspicious", "Happy", "Cynical", "Boring", "Electric", "Fluffy", "Angry", "Lost", 
    "Clever", "Shiny", "Dark", "Silent", "Salty", "Spicy", "Curious", "Awkward", 
    "Radiant", "Grumpy", "Logical", "Wild", "Frosty", "Gloomy", "Brave", "Clumsy"
]

NOUNS = [
    "Panda", "Throwaway", "Potato", "Gecko", "Sock", "Koala", "Gamer", "Chef", 
    "Ninja", "Wizard", "Cactus", "Muffin", "Dragon", "Penguin", "Astronaut", 
    "Kitten", "Waffle", "Goblin", "Cyborg", "Pirate", "Scientist", "Ghost"
]

def generate_username():
    """Generates a highly realistic randomized Reddit username."""
    adj = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    num = random.randint(100, 9999)
    return f"{adj}_{noun}{num}"

# ==========================================
# 2. Local Subreddit Icon Fetcher
# ==========================================
def get_local_subreddit_icon(subreddit_name):
    """
    Checks if a local icon exists at static/images/subreddits/<name>.png
    Returns the absolute formatted file path for HTML if it exists.
    """
    base_dir = os.path.join(os.getcwd(), "static", "images", "subreddits")
    icon_path = os.path.join(base_dir, f"{subreddit_name}.png")
    
    if os.path.exists(icon_path):
        return os.path.abspath(icon_path).replace('\\', '/')
    else:
        return None

# ==========================================
# 3. HTML / CSS Template
# ==========================================
POST_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #ffffff;
            margin: 0;
            padding: 20px;
            color: #1c1c1c;
        }
        #post-container {
            width: 700px;
            background: #fff;
            border: 1px solid #ccc;
            border-radius: 4px;
            overflow: hidden;
            display: inline-block;
        }
        .header {
            padding: 10px 15px;
            display: flex;
            align-items: center;
        }
        .avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background-color: #ff4500;
            margin-right: 10px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .avatar img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .meta-info {
            display: flex;
            flex-direction: column;
        }
        .subreddit {
            font-size: 12px;
            font-weight: bold;
        }
        .user-time {
            font-size: 12px;
            color: #787c7e;
        }
        .title {
            font-size: 20px;
            font-weight: 600;
            padding: 0 15px 10px 15px;
            margin: 0;
        }
        .image-container {
            background-color: #000;
            text-align: center;
            max-height: 600px;
            overflow: hidden;
        }
        .image-container img {
            max-width: 100%;
            max-height: 600px;
            object-fit: contain;
        }
        .text-body {
            padding: 15px;
            font-size: 14px;
            line-height: 1.5;
            color: #222222;
            white-space: pre-wrap;
        }
        .footer {
            padding: 10px 15px;
            display: flex;
            gap: 10px;
            border-top: 1px solid #edeff1;
        }
        .action-button {
            display: flex;
            align-items: center;
            background-color: #eaedef;
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: bold;
            color: #0f1a1c;
        }
    </style>
</head>
<body>
    <div id="post-container">
        <div class="header">
            <div class="avatar">
                {% if subreddit_icon %}
                    <img src="file:///{{ subreddit_icon }}" alt="Subreddit Icon">
                {% else %}
                    <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" style="width:20px; height:20px; fill:white;"><path d="M10 15c-2.4 0-4.8-.6-6.8-1.8l1-1.6c1.7 1 3.7 1.5 5.8 1.5s4.1-.5 5.8-1.5l1 1.6C14.8 14.4 12.4 15 10 15zm4.8-5.8c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5zm-9.6 0c-.8 0-1.5-.7-1.5-1.5S4.4 6.2 5.2 6.2 6.7 6.9 6.7 7.7s-.7 1.5-1.5 1.5zM10 2C5.6 2 2 5.6 2 10s3.6 8 8 8 8-3.6 8-8-3.6-8-8-8z"></path></svg>
                {% endif %}
            </div>
            <div class="meta-info">
                <span class="subreddit">r/{{ subreddit }}</span>
                <span class="user-time">{{ username }} • {{ time_ago }}h ago</span>
            </div>
        </div>
        
        <h2 class="title">{{ title }}</h2>
        
        <div class="image-container">
            <img src="file:///{{ image_path }}" alt="Post Image">
        </div>
        
        {% if text %}
        <div class="text-body">{{ text }}</div>
        {% endif %}
        
        <div class="footer">
            <div class="action-button">⬆ {{ upvotes }} ⬇</div>
            <div class="action-button">💬 {{ comments }}</div>
            <div class="action-button">➦ Share</div>
        </div>
    </div>
</body>
</html>
"""

# ==========================================
# 4. Main Rendering Logic
# ==========================================
def render_post_sync(config: dict, output_filename: str):
    image_path = os.path.abspath(config['image'])
    config['image_path'] = image_path.replace('\\', '/') 

    config['upvotes'] = config.get('upvotes') or random.randint(15, 8000)
    config['comments'] = config.get('comments') or random.randint(5, 500)
    config['time_ago'] = config.get('time_ago') or random.randint(1, 18)
    config['username'] = config.get('username') or generate_username()
    config['subreddit_icon'] = get_local_subreddit_icon(config['subreddit'])

    template = Template(POST_TEMPLATE)
    rendered_html = template.render(**config)

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1200,1200") 

    with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode='w', encoding='utf-8') as temp_file:
        temp_file.write(rendered_html)
        temp_file_path = temp_file.name

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(f"file://{os.path.abspath(temp_file_path)}")

        # Wait a tiny bit for local images to load
        driver.implicitly_wait(1)

        post_element = driver.find_element(By.ID, "post-container")
        post_element.screenshot(output_filename)

    except Exception as e:
        raise Exception(f"Failed to render screenshot: {e}")
    finally:
        if driver:
            driver.quit()
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

# ==========================================
# 5. Discord Cog
# ==========================================
class MockRedditCog(commands.GroupCog, name="reddit"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You don't have permissions to run this command.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def subreddit_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        base_dir = os.path.join(os.getcwd(), "static", "images", "subreddits")
        if not os.path.exists(base_dir):
            return []
        
        subs = []
        for f in os.listdir(base_dir):
            if f.endswith(".png"):
                subs.append(f[:-4])
                
        return [
            app_commands.Choice(name=sub, value=sub) 
            for sub in subs if current.lower() in sub.lower()
        ][:25]

    @app_commands.command(name="create", description="Generate a highly realistic mock Reddit post image.")
    @app_commands.describe(
        subreddit="The subreddit name (without 'r/')",
        title="The title of the post",
        image="The main image to embed in the post",
        text="Optional body text for the post",
        upvotes="Optional specific upvote count",
        comments="Optional specific comment count"
    )
    @app_commands.autocomplete(subreddit=subreddit_autocomplete)
    async def create_post(
        self, 
        interaction: discord.Interaction, 
        subreddit: str, 
        title: str, 
        image: discord.Attachment, 
        text: str = None, 
        upvotes: int = None, 
        comments: int = None
    ):
        if not image.content_type or not image.content_type.startswith('image/'):
            return await interaction.response.send_message("❌ Please upload a valid image file.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Temporary files to handle the attachment and output
        _, img_ext = os.path.splitext(image.filename)
        temp_img_fd, temp_img_path = tempfile.mkstemp(suffix=img_ext)
        os.close(temp_img_fd)
        
        output_filename = temp_img_path.replace(img_ext, "_rendered.png")

        try:
            await image.save(temp_img_path)

            config = {
                'subreddit': subreddit.strip(),
                'title': title.strip(),
                'image': temp_img_path,
                'text': text.strip() if text else None,
                'upvotes': upvotes,
                'comments': comments
            }

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, render_post_sync, config, output_filename)

            if os.path.exists(output_filename):
                file = discord.File(fp=output_filename, filename=f"reddit_{subreddit}.png")
                await interaction.channel.send(file=file)
                await interaction.followup.send("✅ Post generated successfully!", ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to generate the image. Ensure Chromium and ChromeDriver are installed.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred during rendering: {e}", ephemeral=True)
            print(f"MockReddit Error: {e}")
            
        finally:
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)
            if os.path.exists(output_filename):
                os.remove(output_filename)

async def setup(bot):
    await bot.add_cog(MockRedditCog(bot))