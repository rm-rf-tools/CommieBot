import discord
from discord import app_commands
from discord.ext import commands
import os
import time
from typing import List
from database import DatabaseController

active_sessions = {}

# ==========================================
#          APPLICANT TAKING FLOW UI
# ==========================================

class ApplicantSetupModal(discord.ui.Modal, title="Applicant Information"):
    pref_name = discord.ui.TextInput(label="Preferred Name", placeholder="What should we call you?", required=True)
    pronouns = discord.ui.TextInput(label="Pronouns", placeholder="e.g. they/them, she/her, he/him", required=True)

    def __init__(self, form_id: int, form_name: str):
        super().__init__()
        self.form_id = form_id
        self.form_name = form_name

    async def on_submit(self, interaction: discord.Interaction):
        applicant = await DatabaseController.create_applicant(
            str(interaction.guild_id), str(interaction.user.id), 
            interaction.user.name, self.pref_name.value, self.pronouns.value
        )
        await start_form_session(interaction, self.form_id, self.form_name, applicant)


class TextAnswerModal(discord.ui.Modal, title="Answer Question"):
    answer = discord.ui.TextInput(label="Your Answer", style=discord.TextStyle.paragraph, required=True, max_length=3500)

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.session["answers"][self.view.q.id] = self.answer.value
        self.view.session["current_idx"] += 1
        await render_next_question(interaction, self.view.session)


class FeedbackModal(discord.ui.Modal, title="Final Steps"):
    feedback = discord.ui.TextInput(
        label="Any Feedback or Questions?", 
        style=discord.TextStyle.paragraph, 
        required=False,
        placeholder="Type here, or leave blank to submit."
    )

    def __init__(self, session):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        feedback_text = self.feedback.value
        
        # Log feedback to a local text file rather than the database
        if feedback_text.strip():
            os.makedirs("./data", exist_ok=True)
            with open("./data/form_feedback.txt", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] User: {interaction.user.name} | Form: {self.session['form_name']}\n")
                f.write(f"{feedback_text.strip()}\n")
                f.write("-" * 50 + "\n")

        await DatabaseController.save_form_submission(
            self.session["form_id"], self.session["applicant_id"], self.session["answers"]
        )
        
        if interaction.user.id in active_sessions:
            del active_sessions[interaction.user.id]
        
        embed = discord.Embed(title="✅ Application Submitted!", description="Thank you! We've received your application.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=None)


class QuestionView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=1800)
        self.session = session
        self.q = session["questions"][session["current_idx"]]

        if self.q.question_type == "text":
            btn = discord.ui.Button(label="📝 Type Answer", style=discord.ButtonStyle.primary)
            btn.callback = self.text_callback
            self.add_item(btn)

        elif self.q.question_type == "single":
            options = [o.strip() for o in self.q.options.split(",") if o.strip()]
            if len(options) <= 25:
                # Industry standard 1-click button layout
                for i, opt in enumerate(options):
                    btn = discord.ui.Button(label=opt[:80], style=discord.ButtonStyle.secondary, row=i//5)
                    btn.callback = self.make_single_callback(opt)
                    self.add_item(btn)
            else:
                self.select = discord.ui.Select(placeholder="Select your answer...", options=[discord.SelectOption(label=o[:100]) for o in options], min_values=1, max_values=1)
                self.select.callback = self.single_select_callback
                self.add_item(self.select)

        elif self.q.question_type == "multiple":
            options = [o.strip() for o in self.q.options.split(",") if o.strip()]
            self.select = discord.ui.Select(
                placeholder="Select all that apply...",
                options=[discord.SelectOption(label=o[:100]) for o in options],
                min_values=1, max_values=len(options)
            )
            self.select.callback = self.multi_select_callback
            self.add_item(self.select)

            # A next button appears that enables once they select options from the dropdown
            self.next_btn = discord.ui.Button(label="Next ➔", style=discord.ButtonStyle.success, disabled=True, row=4)
            self.next_btn.callback = self.multi_next_callback
            self.add_item(self.next_btn)

    async def text_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TextAnswerModal(self))

    def make_single_callback(self, option_text):
        async def callback(interaction: discord.Interaction):
            self.session["answers"][self.q.id] = option_text
            self.session["current_idx"] += 1
            await render_next_question(interaction, self.session)
        return callback

    async def single_select_callback(self, interaction: discord.Interaction):
        self.session["answers"][self.q.id] = self.select.values[0]
        self.session["current_idx"] += 1
        await render_next_question(interaction, self.session)

    async def multi_select_callback(self, interaction: discord.Interaction):
        self.next_btn.disabled = False
        await interaction.response.edit_message(view=self)

    async def multi_next_callback(self, interaction: discord.Interaction):
        self.session["answers"][self.q.id] = ", ".join(self.select.values)
        self.session["current_idx"] += 1
        await render_next_question(interaction, self.session)


class EndFormView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=1800)
        self.session = session

    @discord.ui.button(label="Provide Feedback & Submit", style=discord.ButtonStyle.success)
    async def finish_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal(self.session))


async def start_form_session(interaction: discord.Interaction, form_id: int, form_name: str, applicant):
    questions = await DatabaseController.get_form_questions(form_id)
    if not questions:
        return await interaction.response.send_message("❌ This form has no questions configured yet.", ephemeral=True)

    session = {
        "form_id": form_id,
        "form_name": form_name,
        "applicant_id": applicant.id,
        "questions": questions,
        "current_idx": 0,
        "answers": {}
    }
    active_sessions[interaction.user.id] = session
    
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    await render_next_question(interaction, session, is_first=True)

async def render_next_question(interaction: discord.Interaction, session: dict, is_first=False):
    idx = session["current_idx"]
    questions = session["questions"]

    if idx >= len(questions):
        embed = discord.Embed(title="🏁 Final Step", description="You have answered all the questions!\nClick below to leave optional feedback and finalize your submission.", color=discord.Color.purple())
        view = EndFormView(session)
    else:
        q = questions[idx]
        embed = discord.Embed(title=f"Question {idx+1} of {len(questions)}", description=f"**{q.question_text}**", color=discord.Color.blue())
        if q.question_type == 'multiple':
            embed.set_footer(text="Select options from the dropdown, then click Next.")
        elif q.question_type == 'single':
            embed.set_footer(text="Click an option to instantly save and advance.")
        view = QuestionView(session)

    if is_first:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

# ==========================================
#          REVIEW APPLICATIONS UI
# ==========================================

class ReviewPaginationView(discord.ui.View):
    def __init__(self, submissions, guild_id: str):
        super().__init__(timeout=900)
        self.submissions = submissions # List of tuples: (submission, template, applicant)
        self.current_idx = 0
        self.guild_id = guild_id
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_idx == 0
        self.next_btn.disabled = self.current_idx == len(self.submissions) - 1

    async def generate_embed(self):
        sub, template, app = self.submissions[self.current_idx]
        embed = discord.Embed(
            title=f"📝 Review: {template.name}", 
            description=f"**Applicant:** <@{app.user_id}> ({app.username})\n**Pref Name:** {app.preferred_name}\n**Pronouns:** {app.pronouns}\n**Date:** <t:{sub.submitted_at}:F>",
            color=discord.Color.gold()
        )
        
        answers = await DatabaseController.get_submission_answers(sub.id)
        for q_text, a_text in answers:
            embed.add_field(name=q_text[:256], value=a_text[:1024], inline=False)
            
        embed.set_footer(text=f"Application {self.current_idx + 1} of {len(self.submissions)} | Status: {sub.status.upper()}")
        return embed

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary, custom_id="prev", row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_idx -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="next", row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_idx += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, row=1)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub = self.submissions[self.current_idx][0]
        await DatabaseController.update_submission_status(sub.id, "confirmed")
        sub.status = "confirmed"
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="⏳ Set Pending", style=discord.ButtonStyle.primary, row=1)
    async def pending_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub = self.submissions[self.current_idx][0]
        await DatabaseController.update_submission_status(sub.id, "pending")
        sub.status = "pending"
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, row=1)
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub = self.submissions[self.current_idx][0]
        await DatabaseController.update_submission_status(sub.id, "denied")
        sub.status = "denied"
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

# ==========================================
#          ADMIN MANAGEMENT UI
# ==========================================

class CreateFormModal(discord.ui.Modal, title="Create New Form"):
    name = discord.ui.TextInput(label="Form Name", placeholder="e.g. Officer Application", required=True)
    desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await DatabaseController.create_form(self.parent_view.guild_id, self.name.value, self.desc.value)
        await self.parent_view.refresh(interaction)

class AddQuestionModal(discord.ui.Modal, title="Add Form Question"):
    q_text = discord.ui.TextInput(label="Question Text", style=discord.TextStyle.paragraph, required=True)
    options = discord.ui.TextInput(label="Options (Comma separated, if applicable)", required=False, placeholder="Option A, Option B, Option C")

    def __init__(self, form_id: int, q_type: str, parent_view):
        super().__init__()
        self.form_id = form_id
        self.q_type = q_type
        self.parent_view = parent_view
        if q_type == "text":
            self.remove_item(self.options)

    async def on_submit(self, interaction: discord.Interaction):
        opts = self.options.value if hasattr(self, 'options') else None
        await DatabaseController.add_form_question(self.form_id, self.q_text.value, self.q_type, opts)
        await self.parent_view.refresh(interaction)

class EditFormView(discord.ui.View):
    def __init__(self, guild_id: str, form, main_view):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.form = form
        self.main_view = main_view

    async def refresh(self, interaction: discord.Interaction):
        questions = await DatabaseController.get_form_questions(self.form.id)
        embed = discord.Embed(title=f"🛠️ Managing: {self.form.name}", description=self.form.description, color=discord.Color.orange())
        
        q_list = ""
        for i, q in enumerate(questions):
            type_lbl = "[TEXT]" if q.question_type == 'text' else f"[{q.question_type.upper()}]"
            q_list += f"**{i+1}.** {type_lbl} {q.question_text}\n"
        
        if not q_list:
            q_list = "*No questions added yet.*"
            
        embed.add_field(name="Current Questions", value=q_list[:1024])
        
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Add Text Q", style=discord.ButtonStyle.primary, row=0)
    async def add_text(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await interaction.response.send_modal(AddQuestionModal(self.form.id, "text", self))

    @discord.ui.button(label="Add Single Choice Q", style=discord.ButtonStyle.secondary, row=0)
    async def add_single(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await interaction.response.send_modal(AddQuestionModal(self.form.id, "single", self))

    @discord.ui.button(label="Add Multi Choice Q", style=discord.ButtonStyle.secondary, row=0)
    async def add_multi(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await interaction.response.send_modal(AddQuestionModal(self.form.id, "multiple", self))

    @discord.ui.button(label="Delete Form", style=discord.ButtonStyle.danger, row=1)
    async def del_form(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await DatabaseController.delete_form(self.form.id)
        await self.main_view.refresh(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await self.main_view.refresh(interaction)

class ManageFormsView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=600)
        self.guild_id = guild_id

    async def refresh(self, interaction: discord.Interaction):
        self.clear_items()
        forms = await DatabaseController.get_all_forms(self.guild_id)
        
        embed = discord.Embed(title="📋 Form Management", description="Manage or create custom forms.", color=discord.Color.purple())

        if forms:
            options = [discord.SelectOption(label=f.name, value=str(f.id), description=f.description[:50]) for f in forms[:25]]
            select = discord.ui.Select(placeholder="Select a form to edit...", options=options)
            
            async def select_callback(inter: discord.Interaction):
                form = await DatabaseController.get_form_by_id(int(select.values[0]))
                edit_view = EditFormView(self.guild_id, form, self)
                await edit_view.refresh(inter)
                
            select.callback = select_callback
            self.add_item(select)

        create_btn = discord.ui.Button(label="➕ Create New Form", style=discord.ButtonStyle.success)
        async def create_callback(inter: discord.Interaction):
            await inter.response.send_modal(CreateFormModal(self))
        create_btn.callback = create_callback
        self.add_item(create_btn)

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


# ==========================================
#                  COG
# ==========================================

class FormsCog(commands.GroupCog, name="forms"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def form_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        forms = await DatabaseController.get_all_forms(str(interaction.guild_id))
        return [app_commands.Choice(name=f.name, value=f.name) for f in forms if current.lower() in f.name.lower()][:25]

    @app_commands.command(name="apply", description="Start an application/form.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    async def apply_form(self, interaction: discord.Interaction, form_name: str):
        guild_id = str(interaction.guild_id)
        
        form = await DatabaseController.get_form_by_name(guild_id, form_name)
        if not form:
            return await interaction.response.send_message(f"❌ Form **{form_name}** not found.", ephemeral=True)

        applicant = await DatabaseController.get_applicant(guild_id, str(interaction.user.id))
        if applicant:
            has_recent = await DatabaseController.check_recent_submission(form.id, applicant.id)
            if has_recent:
                return await interaction.response.send_message("❌ You have already submitted an application to this form within the last 30 days.", ephemeral=True)
            
            await start_form_session(interaction, form.id, form.name, applicant)
        else:
            await interaction.response.send_modal(ApplicantSetupModal(form.id, form.name))

    @app_commands.command(name="manage", description="Interactive UI to manage, create, and edit forms.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def manage_forms(self, interaction: discord.Interaction):
        view = ManageFormsView(str(interaction.guild_id))
        embed = discord.Embed(title="Loading...", color=discord.Color.purple())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.refresh(interaction)

    @app_commands.command(name="review", description="Review pending form applications.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def review_forms(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        submissions = await DatabaseController.get_pending_submissions(str(interaction.guild_id))
        
        if not submissions:
            return await interaction.followup.send("✅ There are no pending applications to review!")
            
        view = ReviewPaginationView(submissions, str(interaction.guild_id))
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    # --- CLI BACKUP COMMANDS ---
    @app_commands.command(name="backup_create", description="CLI Backup: Create a form.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_create(self, interaction: discord.Interaction, name: str, description: str):
        await DatabaseController.create_form(str(interaction.guild_id), name, description)
        await interaction.response.send_message(f"✅ Created form: **{name}**", ephemeral=True)

    @app_commands.command(name="backup_add_question", description="CLI Backup: Add a question to a form.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    @app_commands.choices(q_type=[
        app_commands.Choice(name="Text (Paragraph)", value="text"),
        app_commands.Choice(name="Single Choice", value="single"),
        app_commands.Choice(name="Multiple Choice", value="multiple"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_add_q(self, interaction: discord.Interaction, form_name: str, q_type: app_commands.Choice[str], text: str, options: str = None):
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if not form:
            return await interaction.response.send_message("❌ Form not found.", ephemeral=True)
        
        await DatabaseController.add_form_question(form.id, text, q_type.value, options)
        await interaction.response.send_message(f"✅ Question added to **{form_name}**.", ephemeral=True)

    @app_commands.command(name="backup_delete", description="CLI Backup: Delete a form.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_delete(self, interaction: discord.Interaction, form_name: str):
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if form:
            await DatabaseController.delete_form(form.id)
            await interaction.response.send_message(f"🗑️ Deleted form **{form_name}**.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Form not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FormsCog(bot))