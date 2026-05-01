"""
filename: forms.py
description: Create and manage interactive forms/applications with reviews and automated status updates.
Views:
    - RegistrationModal: Initial applicant registration for preferred name and pronouns.
    - FormWizardView: Navigates through form questions (text, single/multiple choice).
    - TextAnswerModal: Input modal for text-based form questions.
    - FeedbackModal: Final step for feedback before form submission.
    - FormAdminView: Main management interface for admins to see existing forms.
    - FormDetailView: Interface for editing a specific form's questions and settings.
    - AddQuestionTypeView: Menu to select question type (text, single, multiple).
    - FormReviewView: Interface for reviewing and approving/denying pending submissions.
Commands:
    - /forms apply <form_name>: Apply for a form/application role. (User)
    - /forms admin: Open the GUI to manage, create, and edit forms. (Forms Admin / Admin: Manage Guild)
    - /forms review: Review pending form applications. (Forms Admin / Admin: Manage Guild)
    - /forms set_role <role>: Set the admin role capable of managing and reviewing forms. (Admin: Manage Guild)
    - /forms create_cmd <name> <description> [cooldown_days]: Fallback: Create a form via text command. (Forms Admin / Admin: Manage Guild)
    - /forms add_question_cmd <form_name> <q_type> <text> [options]: Fallback: Add a question via text command. (Forms Admin / Admin: Manage Guild)
    - /forms delete_cmd <form_name>: Fallback: Delete a form via text command. (Forms Admin / Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from db import DatabaseController

# ---------------------------------------------------------
# PERMISSION CHECK
# ---------------------------------------------------------
async def check_forms_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.manage_guild:
        return True
    role_id = await DatabaseController.get_forms_role(str(interaction.guild_id))
    if role_id and any(str(r.id) == role_id for r in interaction.user.roles):
        return True
    return False

# ---------------------------------------------------------
# APPLICANT WIZARD UI
# ---------------------------------------------------------
class RegistrationModal(discord.ui.Modal, title="Applicant Registration"):
    preferred_name = discord.ui.TextInput(label="Preferred Name", placeholder="e.g. John/Jane", required=True)
    pronouns = discord.ui.TextInput(label="Pronouns", placeholder="e.g. they/them", required=True)

    def __init__(self, form, questions):
        super().__init__()
        self.form = form
        self.questions = questions

    async def on_submit(self, interaction: discord.Interaction):
        applicant = await DatabaseController.create_applicant(
            str(interaction.guild_id), str(interaction.user.id),
            interaction.user.name, self.preferred_name.value.strip(), self.pronouns.value.strip()
        )
        view = FormWizardView(self.form, self.questions, applicant)
        await view.start(interaction)

class FeedbackModal(discord.ui.Modal, title="Final Step: Feedback"):
    feedback = discord.ui.TextInput(
        label="Any feedback or questions for us?",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Optional: Type your questions or feedback here..."
    )

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        await self.wizard.submit_form(interaction, self.feedback.value.strip())

class TextAnswerModal(discord.ui.Modal, title="Answer Question"):
    answer_input = discord.ui.TextInput(
        label="Your Answer",
        style=discord.TextStyle.paragraph,
        required=True
    )

    def __init__(self, wizard_view, question):
        super().__init__()
        self.wizard_view = wizard_view
        self.question = question

    async def on_submit(self, interaction: discord.Interaction):
        self.wizard_view.answers[self.question.id] = self.answer_input.value.strip()
        self.wizard_view.index += 1
        await self.wizard_view.update_ui(interaction)

class FormWizardView(discord.ui.View):
    def __init__(self, form, questions, applicant):
        super().__init__(timeout=900)
        self.form = form
        self.questions = questions
        self.applicant = applicant
        self.index = 0
        self.answers = {}

    async def start(self, interaction: discord.Interaction):
        await self.update_ui(interaction)

    async def update_ui(self, interaction: discord.Interaction):
        self.clear_items()
        
        # Reached the end -> Ask for Feedback
        if self.index >= len(self.questions):
            embed = discord.Embed(
                title=f"{self.form.name} - Almost Done!", 
                description="You've answered all the questions. Do you have any feedback or questions for us before submitting?",
                color=discord.Color.green()
            )
            
            btn_feedback = discord.ui.Button(label="Add Feedback & Submit", style=discord.ButtonStyle.primary)
            async def fb_cb(i):
                await i.response.send_modal(FeedbackModal(self))
            btn_feedback.callback = fb_cb
            
            btn_skip = discord.ui.Button(label="Skip & Submit", style=discord.ButtonStyle.success)
            async def skip_cb(i):
                await self.submit_form(i, None)
            btn_skip.callback = skip_cb
            
            btn_back = discord.ui.Button(label="Back to Last Question", style=discord.ButtonStyle.secondary)
            async def back_cb(i):
                self.index -= 1
                await self.update_ui(i)
            btn_back.callback = back_cb

            self.add_item(btn_feedback)
            self.add_item(btn_skip)
            self.add_item(btn_back)
            
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            return

        # Normal Questions
        q = self.questions[self.index]
        embed = discord.Embed(
            title=self.form.name, 
            description=f"**Question {self.index + 1} of {len(self.questions)}**\n\n{q.question_text}",
            color=discord.Color.blue()
        )

        if q.question_type == 'text':
            btn = discord.ui.Button(label="📝 Click to Type Answer", style=discord.ButtonStyle.primary)
            async def text_cb(i):
                await i.response.send_modal(TextAnswerModal(self, q))
            btn.callback = text_cb
            self.add_item(btn)
            
            if q.id in self.answers:
                embed.add_field(name="Current Answer:", value=self.answers[q.id])
                next_btn = discord.ui.Button(label="Next ➡️", style=discord.ButtonStyle.success)
                async def next_cb(i):
                    self.index += 1
                    await self.update_ui(i)
                next_btn.callback = next_cb
                self.add_item(next_btn)

        elif q.question_type in ['single', 'multiple']:
            opts = [o.strip() for o in q.options.split(',') if o.strip()]
            max_v = 1 if q.question_type == 'single' else len(opts)
            placeholder = "Select an option..." if max_v == 1 else "Select all that apply..."
            sel = discord.ui.Select(placeholder=placeholder, options=[discord.SelectOption(label=o[:100]) for o in opts], max_values=max_v)
            
            async def sel_cb(i):
                self.answers[q.id] = ", ".join(sel.values)
                self.index += 1
                await self.update_ui(i)
            sel.callback = sel_cb
            self.add_item(sel)

        if self.index > 0:
            prev_btn = discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=4)
            async def prev_cb(i):
                self.index -= 1
                await self.update_ui(i)
            prev_btn.callback = prev_cb
            self.add_item(prev_btn)

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def submit_form(self, interaction: discord.Interaction, feedback: str):
        # We automatically append the feedback to the answer of the last question!
        if feedback and self.questions:
            last_q_id = self.questions[-1].id
            if last_q_id in self.answers:
                self.answers[last_q_id] += f"\n\n**[Applicant Feedback/Questions]:**\n{feedback}"
                
        await DatabaseController.save_form_submission(self.form.id, self.applicant.id, self.answers)
        
        embed = discord.Embed(title="✅ Submitted successfully!", description="Thank you. Your application is now pending review.", color=discord.Color.green())
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=None)
        else:
            await interaction.response.send_message(embed=embed, view=None, ephemeral=True)


# ---------------------------------------------------------
# ADMIN & REVIEW UI
# ---------------------------------------------------------
class CreateFormModal(discord.ui.Modal, title="Create New Form"):
    f_name = discord.ui.TextInput(label="Form Name", required=True)
    f_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)
    f_cool = discord.ui.TextInput(label="Cooldown (Days between applying)", default="30", required=True)

    def __init__(self, admin_view):
        super().__init__()
        self.admin_view = admin_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cool = int(self.f_cool.value)
        except ValueError:
            cool = 0
            
        await DatabaseController.create_form(str(interaction.guild_id), self.f_name.value.strip(), self.f_desc.value.strip(), cool)
        await self.admin_view.fetch()
        await self.admin_view.build()
        await interaction.response.edit_message(content=f"Created form: **{self.f_name.value}**", embed=self.admin_view.generate_embed(), view=self.admin_view)


class AddQuestionModal(discord.ui.Modal, title="Add Question"):
    q_text = discord.ui.TextInput(label="Question Text", style=discord.TextStyle.paragraph, required=True)
    q_opts = discord.ui.TextInput(label="Options (Comma separated)", required=False, placeholder="For multiple choice. Leave blank if Text type.")

    def __init__(self, detail_view, q_type):
        super().__init__()
        self.detail_view = detail_view
        self.q_type = q_type
        if q_type in ['single', 'multiple']:
            self.q_opts.required = True

    async def on_submit(self, interaction: discord.Interaction):
        await DatabaseController.add_form_question(self.detail_view.form.id, self.q_text.value.strip(), self.q_type, self.q_opts.value.strip())
        await self.detail_view.fetch()
        await self.detail_view.build()
        await interaction.response.edit_message(embed=self.detail_view.generate_embed(), view=self.detail_view)

class AddQuestionTypeView(discord.ui.View):
    def __init__(self, detail_view):
        super().__init__()
        self.detail_view = detail_view

        sel = discord.ui.Select(options=[
            discord.SelectOption(label="Text (Open Ended)", value="text"),
            discord.SelectOption(label="Single Choice", value="single"),
            discord.SelectOption(label="Multiple Choice", value="multiple"),
        ], placeholder="Select Question Type...")
        
        async def sel_cb(i):
            q_type = sel.values[0]
            await i.response.send_modal(AddQuestionModal(self.detail_view, q_type))
        sel.callback = sel_cb
        self.add_item(sel)

        btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_cb(i):
            await self.detail_view.build()
            await i.response.edit_message(embed=self.detail_view.generate_embed(), view=self.detail_view)
        btn.callback = cancel_cb
        self.add_item(btn)

class FormDetailView(discord.ui.View):
    def __init__(self, form, admin_view):
        super().__init__(timeout=600)
        self.form = form
        self.admin_view = admin_view
        self.questions = []

    async def fetch(self):
        self.questions = await DatabaseController.get_form_questions(self.form.id)

    def generate_embed(self):
        e = discord.Embed(title=f"Editing Form: {self.form.name}", description=self.form.description, color=discord.Color.blue())
        e.add_field(name="Cooldown Days", value=str(self.form.cooldown_days), inline=False)
        
        if not self.questions:
            e.add_field(name="Questions", value="*No questions added yet.*")
        else:
            for i, q in enumerate(self.questions):
                opts = f"\nOptions: *{q.options}*" if q.options else ""
                val = f"**Type:** {q.question_type}{opts}"
                e.add_field(name=f"{i+1}. {q.question_text[:200]}", value=val, inline=False)
        return e

    async def build(self):
        self.clear_items()
        
        btn_add = discord.ui.Button(label="➕ Add Question", style=discord.ButtonStyle.primary)
        async def add_cb(i):
            view = AddQuestionTypeView(self)
            await i.response.edit_message(embed=self.generate_embed(), view=view)
        btn_add.callback = add_cb
        self.add_item(btn_add)

        if self.questions:
            del_sel = discord.ui.Select(placeholder="Select a question to delete...", options=[
                discord.SelectOption(label=f"Delete Q{i+1}: {q.question_text[:50]}", value=str(q.id)) for i, q in enumerate(self.questions)
            ][:25])
            async def del_cb(i):
                await DatabaseController.delete_form_question(int(del_sel.values[0]))
                await self.fetch()
                await self.build()
                await i.response.edit_message(embed=self.generate_embed(), view=self)
            del_sel.callback = del_cb
            self.add_item(del_sel)

        btn_back = discord.ui.Button(label="⬅️ Back to Forms List", style=discord.ButtonStyle.secondary, row=2)
        async def back_cb(i):
            await self.admin_view.fetch()
            await self.admin_view.build()
            await i.response.edit_message(embed=self.admin_view.generate_embed(), view=self.admin_view)
        btn_back.callback = back_cb
        self.add_item(btn_back)
        
        btn_del = discord.ui.Button(label="🗑️ Delete Entire Form", style=discord.ButtonStyle.danger, row=2)
        async def del_form_cb(i):
            await DatabaseController.delete_form(self.form.id)
            await self.admin_view.fetch()
            await self.admin_view.build()
            await i.response.edit_message(content="Form deleted.", embed=self.admin_view.generate_embed(), view=self.admin_view)
        btn_del.callback = del_form_cb
        self.add_item(btn_del)

class FormAdminView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.forms = []

    async def fetch(self):
        self.forms = await DatabaseController.get_all_forms(self.guild_id)

    def generate_embed(self):
        return discord.Embed(title="⚙️ Form Management", description="Create, edit, or delete interactive forms.", color=discord.Color.purple())

    async def build(self):
        self.clear_items()
        if self.forms:
            sel = discord.ui.Select(options=[discord.SelectOption(label=f.name[:100], value=str(f.id)) for f in self.forms][:25], placeholder="Select a form to manage...")
            async def sel_cb(i):
                form_id = int(sel.values[0])
                form = await DatabaseController.get_form_by_id(form_id)
                detail_view = FormDetailView(form, self)
                await detail_view.fetch()
                await detail_view.build()
                await i.response.edit_message(embed=detail_view.generate_embed(), view=detail_view)
            sel.callback = sel_cb
            self.add_item(sel)

        btn = discord.ui.Button(label="➕ Create New Form", style=discord.ButtonStyle.success)
        async def btn_cb(i):
            await i.response.send_modal(CreateFormModal(self))
        btn.callback = btn_cb
        self.add_item(btn)

class FormReviewView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.pending = []

    async def fetch(self):
        self.pending = await DatabaseController.get_pending_submissions(self.guild_id)

    def generate_empty_embed(self):
        return discord.Embed(title="✅ All Caught Up!", description="There are no pending form submissions.", color=discord.Color.green())

    async def build(self):
        self.clear_items()
        if not self.pending:
            self.add_item(discord.ui.Button(label="Queue Empty", disabled=True))
            return

        opts = []
        for sub, form, app in self.pending[:25]:
            opts.append(discord.SelectOption(label=f"[{form.name}] {app.username}", description=app.preferred_name, value=str(sub.id)))
        
        sel = discord.ui.Select(options=opts, placeholder="Select submission to review...")
        async def sel_cb(i):
            sub_id = int(sel.values[0])
            sub_tuple = next((x for x in self.pending if x[0].id == sub_id), None)
            if sub_tuple:
                await self.show_submission(i, sub_tuple)
        sel.callback = sel_cb
        self.add_item(sel)

    async def show_submission(self, interaction, sub_tuple):
        sub, form, app = sub_tuple
        answers = await DatabaseController.get_submission_answers(sub.id)
        
        emb = discord.Embed(title=f"Reviewing: {form.name}", color=discord.Color.gold())
        emb.add_field(name="Applicant Details", value=f"**User:** <@{app.user_id}>\n**Preferred Name:** {app.preferred_name}\n**Pronouns:** {app.pronouns}", inline=False)
        
        for q_text, a_text in answers:
            a_val = a_text[:1021] + "..." if len(a_text) > 1024 else a_text
            emb.add_field(name=q_text[:256], value=a_val, inline=False)
            
        view = discord.ui.View()
        
        async def process_decision(i, decision):
            await DatabaseController.update_submission_status(sub.id, decision)
            await self.fetch()
            await self.build()
            if self.pending:
                await i.response.edit_message(content=f"Submission **{decision}**! Select the next one:", embed=discord.Embed(title="Queue status", description=f"{len(self.pending)} remaining.", color=discord.Color.orange()), view=self)
            else:
                await i.response.edit_message(content=f"Submission **{decision}**!", embed=self.generate_empty_embed(), view=self)

        btn_app = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success)
        btn_app.callback = lambda i: process_decision(i, "approved")
        
        btn_den = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger)
        btn_den.callback = lambda i: process_decision(i, "denied")
        
        btn_back = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def back_cb(i):
            await i.response.edit_message(embed=discord.Embed(title="Returning to Queue"), view=self)
        btn_back.callback = back_cb

        view.add_item(btn_app)
        view.add_item(btn_den)
        view.add_item(btn_back)
        
        await interaction.response.edit_message(embed=emb, view=view)


# ---------------------------------------------------------
# DISCORD COG
# ---------------------------------------------------------
class FormsCog(commands.GroupCog, name="forms"):
    def __init__(self, bot):
        self.bot = bot

    async def form_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        forms = await DatabaseController.get_all_forms(str(interaction.guild_id))
        return [app_commands.Choice(name=f.name, value=f.name) for f in forms if current.lower() in f.name.lower()][:25]

    @app_commands.command(name="apply", description="Apply for a form/application role.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    async def forms_apply(self, interaction: discord.Interaction, form_name: str):
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if not form:
            return await interaction.response.send_message(f"❌ Form '{form_name}' not found.", ephemeral=True)
            
        questions = await DatabaseController.get_form_questions(form.id)
        if not questions:
            return await interaction.response.send_message("❌ This form has no questions and isn't ready.", ephemeral=True)
            
        app = await DatabaseController.get_applicant(str(interaction.guild_id), str(interaction.user.id))
        
        if app:
            recent = await DatabaseController.check_recent_submission(form.id, app.id, form.cooldown_days)
            if recent:
                return await interaction.response.send_message(f"⏳ You have applied recently! There is a {form.cooldown_days} day cooldown.", ephemeral=True)
            
            view = FormWizardView(form, questions, app)
            await view.start(interaction)
        else:
            await interaction.response.send_modal(RegistrationModal(form, questions))

    @app_commands.command(name="admin", description="Open the GUI to manage, create, and edit forms.")
    @app_commands.check(check_forms_admin)
    async def forms_admin(self, interaction: discord.Interaction):
        view = FormAdminView(str(interaction.guild_id))
        await view.fetch()
        await view.build()
        await interaction.response.send_message(embed=view.generate_embed(), view=view, ephemeral=True)

    @app_commands.command(name="review", description="Review pending form applications.")
    @app_commands.check(check_forms_admin)
    async def forms_review(self, interaction: discord.Interaction):
        view = FormReviewView(str(interaction.guild_id))
        await view.fetch()
        await view.build()
        if not view.pending:
            await interaction.response.send_message(embed=view.generate_empty_embed(), ephemeral=True)
        else:
            await interaction.response.send_message(embed=discord.Embed(title="Review Queue", description=f"{len(view.pending)} pending applications."), view=view, ephemeral=True)

    @app_commands.command(name="set_role", description="Set the admin role capable of managing and reviewing forms.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def forms_set_role(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_forms_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ Users with the {role.mention} role can now manage forms.", ephemeral=True)


    # ==========================
    # Text Command Fallbacks
    # ==========================
    @app_commands.command(name="create_cmd", description="Fallback: Create a form via text command")
    @app_commands.check(check_forms_admin)
    async def create_cmd(self, interaction: discord.Interaction, name: str, description: str, cooldown_days: int = 30):
        await DatabaseController.create_form(str(interaction.guild_id), name, description, cooldown_days)
        await interaction.response.send_message(f"✅ Form **{name}** created via command.", ephemeral=True)

    @app_commands.command(name="add_question_cmd", description="Fallback: Add a question via text command")
    @app_commands.autocomplete(form_name=form_autocomplete)
    @app_commands.choices(q_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Single Choice", value="single"),
        app_commands.Choice(name="Multiple Choice", value="multiple")
    ])
    @app_commands.check(check_forms_admin)
    async def add_question_cmd(self, interaction: discord.Interaction, form_name: str, q_type: app_commands.Choice[str], text: str, options: Optional[str] = None):
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if not form: return await interaction.response.send_message("❌ Form not found.", ephemeral=True)
        
        await DatabaseController.add_form_question(form.id, text, q_type.value, options)
        await interaction.response.send_message(f"✅ Added {q_type.name} question to **{form.name}**.", ephemeral=True)

    @app_commands.command(name="delete_cmd", description="Fallback: Delete a form via text command")
    @app_commands.autocomplete(form_name=form_autocomplete)
    @app_commands.check(check_forms_admin)
    async def delete_cmd(self, interaction: discord.Interaction, form_name: str):
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if not form: return await interaction.response.send_message("❌ Form not found.", ephemeral=True)
        
        await DatabaseController.delete_form(form.id)
        await interaction.response.send_message(f"🗑️ Deleted **{form.name}**.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FormsCog(bot))
