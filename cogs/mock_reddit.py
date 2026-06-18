"""
filename: mock_reddit.py
description: Generates highly realistic mock Reddit posts using a Jinja2 template and headless Selenium.
Views:
    - None
Commands:
    - /reddit create <subreddit> <title> <image> [theme] [text] [upvotes] [comments]: Create a mock Reddit post and send it to the channel. (User)
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
    adj = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    num = random.randint(100, 9999)
    return f"{adj}_{noun}{num}"

# ==========================================
# 2. Local Subreddit Icon Fetcher
# ==========================================
def get_local_subreddit_icon(subreddit_name):
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
        :root {
            --bg-color: #0b1416;
            --text-primary: #f2f4f5;
            --text-secondary: #818384;
            --btn-bg: #1a282d;
        }
        #post-container.light {
            --bg-color: #ffffff;
            --text-primary: #1c1c1c;
            --text-secondary: #787c7e;
            --btn-bg: #eaedef;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: transparent;
            margin: 0;
            padding: 20px;
        }
        #post-container {
            width: 700px;
            background-color: var(--bg-color);
            padding: 16px;
            display: inline-block;
            color: var(--text-primary);
            border: 1px solid rgba(129, 131, 132, 0.15); /* Slight border for neatness */
            border-radius: 8px;
        }
        .header-top {
            display: flex;
            align-items: center;
            margin-bottom: 14px;
        }
        .back-icon {
            margin-right: 16px;
            color: var(--text-primary);
            display: flex;
            align-items: center;
        }
        .header-info {
            display: flex;
            align-items: center;
            flex-grow: 1;
        }
        .avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background-color: #ff4500;
            margin-right: 8px;
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
        .meta-column {
            display: flex;
            flex-direction: column;
        }
        .meta-top {
            display: flex;
            align-items: center;
            font-size: 13px;
            font-weight: 700;
        }
        .meta-time {
            color: var(--text-secondary);
            font-weight: 400;
            margin-left: 5px;
        }
        .meta-user {
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 1px;
        }
        .more-icon {
            color: var(--text-secondary);
            display: flex;
            align-items: center;
        }
        .title {
            font-size: 20px;
            font-weight: 500;
            margin: 0 0 14px 0;
            line-height: 1.3;
        }
        .media-wrapper {
            position: relative;
            width: 100%;
            max-height: 650px;
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #000;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .media-blur {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image: url("file:///{{ image_path }}");
            background-size: cover;
            background-position: center;
            filter: blur(25px);
            opacity: 0.45;
            transform: scale(1.2); /* Prevents blur from bleeding soft white edges */
            z-index: 1;
        }
        .media-img {
            position: relative;
            z-index: 2;
            max-width: 100%;
            max-height: 650px;
            object-fit: contain;
        }
        .text-body {
            font-size: 14px;
            line-height: 1.5;
            margin-top: 14px;
            white-space: pre-wrap;
        }
        .footer {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-top: 16px;
        }
        .action-button {
            display: flex;
            align-items: center;
            background-color: var(--btn-bg);
            padding: 6px 14px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            color: var(--text-primary);
            gap: 6px;
        }
        .action-icon {
            width: 20px; 
            height: 20px; 
            fill: none; 
            stroke: currentColor; 
            stroke-width: 2.2; 
            stroke-linecap: round; 
            stroke-linejoin: round;
        }
        .icon-filled {
            fill: currentColor;
            stroke: none;
        }
    </style>
</head>
<body>
    <div id="post-container" class="{{ theme }}">
        <!-- Header -->
        <div class="header-top">
            <div class="back-icon">
                <svg class="action-icon" viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
            </div>
            <div class="header-info">
                <div class="avatar">
                    {% if subreddit_icon %}
                        <img src="file:///{{ subreddit_icon }}" alt="Subreddit Icon">
                    {% else %}
                        <svg viewBox="0 0 20 20" class="icon-filled" style="width:20px; height:20px;"><path d="M10 15c-2.4 0-4.8-.6-6.8-1.8l1-1.6c1.7 1 3.7 1.5 5.8 1.5s4.1-.5 5.8-1.5l1 1.6C14.8 14.4 12.4 15 10 15zm4.8-5.8c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5zm-9.6 0c-.8 0-1.5-.7-1.5-1.5S4.4 6.2 5.2 6.2 6.7 6.9 6.7 7.7s-.7 1.5-1.5 1.5zM10 2C5.6 2 2 5.6 2 10s3.6 8 8 8 8-3.6 8-8-3.6-8-8-8z"></path></svg>
                    {% endif %}
                </div>
                <div class="meta-column">
                    <div class="meta-top">r/{{ subreddit }} <span class="meta-time">• {{ time_ago }}h ago</span></div>
                    <div class="meta-user">{{ username }}</div>
                </div>
            </div>
            <div class="more-icon">
                <svg viewBox="0 0 24 24" class="icon-filled" style="width:24px; height:24px;"><circle cx="5" cy="12" r="2"></circle><circle cx="12" cy="12" r="2"></circle><circle cx="19" cy="12" r="2"></circle></svg>
            </div>
        </div>
        
        <!-- Post Content -->
        <h2 class="title">{{ title }}</h2>
        
        <div class="media-wrapper">
            <div class="media-blur"></div>
            <img class="media-img" src="file:///{{ image_path }}" alt="Post Image">
        </div>
        
        {% if text %}
        <div class="text-body">{{ text }}</div>
        {% endif %}
        
        <!-- Footer Buttons -->
        <div class="footer">
            <div class="action-button">
                <svg class="action-icon" viewBox="0 0 24 24"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
                <span style="margin: 0 4px;">{{ upvotes }}</span>
                <svg class="action-icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline></svg>
            </div>
            <div class="action-button">
                <svg class="action-icon" viewBox="0 0 24 24"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                <span>{{ comments }}</span>
            </div>
            <div class="action-button">
                <svg class="action-icon" viewBox="0 0 24 24"><polyline points="17 1 21 5 17 9"></polyline><path d="M3 11V9a4 4 0 0 1 4-4h14"></path><polyline points="7 23 3 19 7 15"></polyline><path d="M21 13v2a4 4 0 0 1-4 4H3"></path></svg>
            </div>
            <div class="action-button">
                <svg class="action-icon" viewBox="0 0 24 24" style="stroke-width:2;"><path d="M10 15v4a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2h-4"/><polyline points="13 6 10 3 7 6"/><line x1="10" y1="3" x2="10" y2="15"/></svg>
                <span>Share</span>
            </div>
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
    config['theme'] = config.get('theme', 'dark')

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
        theme="Post theme configuration (Default: Dark Mode)",
        text="Optional body text for the post",
        upvotes="Optional specific upvote count",
        comments="Optional specific comment count"
    )
    @app_commands.choices(theme=[
        app_commands.Choice(name="Dark Mode", value="dark"),
        app_commands.Choice(name="Light Mode", value="light")
    ])
    @app_commands.autocomplete(subreddit=subreddit_autocomplete)
    async def create_post(
        self, 
        interaction: discord.Interaction, 
        subreddit: str, 
        title: str, 
        image: discord.Attachment, 
        theme: app_commands.Choice[str] = None,
        text: str = None, 
        upvotes: int = None, 
        comments: int = None
    ):
        if not image.content_type or not image.content_type.startswith('image/'):
            return await interaction.response.send_message("❌ Please upload a valid image file.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

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
                'theme': theme.value if theme else "dark",
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
            print(f"Reddit Error: {e}")
            
        finally:
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)
            if os.path.exists(output_filename):
                os.remove(output_filename)

async def setup(bot):
    await bot.add_cog(MockRedditCog(bot))