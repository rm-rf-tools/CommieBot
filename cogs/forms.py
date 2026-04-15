import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import io
from typing import List
from database import DatabaseController

active_sessions = {}

# --- Helper: Check Form Permissions ---
async def has_form_perms(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.manage_guild:
        return True
    role_id = await DatabaseController.get_forms_role(str(interaction.guild_id))
    if role_id and str(role_id) in [str(r.id) for r in interaction.user.roles]:
        return True
    return False

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

class FeedbackModal(discord.ui.Modal, title="Optional Feedback"):
    feedback = discord.ui.TextInput(
        label="Any Feedback or Questions?", 
        style=discord.TextStyle.paragraph, 
        required=True,
        placeholder="Type your feedback here..."
    )

    def __init__(self, form_name: str):
        super().__init__()
        self.form_name = form_name

    async def on_submit(self, interaction: discord.Interaction):
        feedback_text = self.feedback.value
        
        os.makedirs("./data", exist_ok=True)
        with open("./data/form_feedback.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] User: {interaction.user.name} | Form: {self.form_name}\n")
            f.write(f"{feedback_text.strip()}\n")
            f.write("-" * 50 + "\n")

        embed = discord.Embed(title="✅ Feedback Received", description="Thank you for your input! Your application is already fully submitted.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=None)

class OptionalFeedbackView(discord.ui.View):
    def __init__(self, form_name: str):
        super().__init__(timeout=600)
        self.form_name = form_name

    @discord.ui.button(label="📝 Leave Optional Feedback", style=discord.ButtonStyle.secondary)
    async def feedback_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal(self.form_name))

class QuestionView(discord.ui.View):
    def __init__(self, session, is_last: bool):
        super().__init__(timeout=3000)
        self.session = session
        self.q = session["questions"][session["current_idx"]]
        self.is_last = is_last
        
        self.continue_text = "Save & Submit ➔" if self.is_last else "Save & Continue ➔"

        if self.q.question_type == "text":
            btn = discord.ui.Button(label="📝 Type Answer", style=discord.ButtonStyle.primary)
            btn.callback = self.text_callback
            self.add_item(btn)

        elif self.q.question_type == "single":
            options = [o.strip() for o in self.q.options.split(",") if o.strip()]
            if len(options) <= 25:
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

            self.next_btn = discord.ui.Button(label=self.continue_text, style=discord.ButtonStyle.success, disabled=True, row=4)
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
        num_selected = len(self.select.values)
        self.select.placeholder = f"✅ {num_selected} option{'s' if num_selected > 1 else ''} selected"
        await interaction.response.edit_message(view=self)

    async def multi_next_callback(self, interaction: discord.Interaction):
        self.session["answers"][self.q.id] = ", ".join(self.select.values)
        self.session["current_idx"] += 1
        await render_next_question(interaction, self.session)

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
        await DatabaseController.save_form_submission(
            session["form_id"], session["applicant_id"], session["answers"]
        )
        
        if interaction.user.id in active_sessions:
            del active_sessions[interaction.user.id]

        embed = discord.Embed(
            title="✅ Application Submitted!", 
            description="Thank you! We've successfully received and logged your application.\n\n*If you have any feedback or questions regarding this form, you can optionally submit them below.*", 
            color=discord.Color.green()
        )
        view = OptionalFeedbackView(session["form_name"])
        
        if is_first:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.edit_message(embed=embed, view=view)
            
    else:
        q = questions[idx]
        is_last = (idx == len(questions) - 1)
        action_word = "submit your application." if is_last else "continue."
        
        embed = discord.Embed(title=f"Question {idx+1} of {len(questions)}", description=f"**{q.question_text}**", color=discord.Color.blue())
        
        if q.question_type == 'multiple':
            embed.set_footer(text=f"Select options from the dropdown, then click Save to {action_word}")
        elif q.question_type == 'single':
            embed.set_footer(text=f"Click an option below to instantly save and {action_word}")
        elif q.question_type == 'text':
            embed.set_footer(text=f"Click the button to type your answer and {action_word}")
            
        view = QuestionView(session, is_last=is_last)

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
        self.submissions = submissions 
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
        
        total_chars = len(embed.title) + len(embed.description)
        
        for q_text, a_text in answers:
            q_title = q_text[:250]
            a_val = a_text or "*No answer*"
            
            # Truncate field value to keep well under Discord's 1024 limit
            if len(a_val) > 800:
                a_val = a_val[:797] + "..."
                
            # Prevent overall embed from crashing (Discord limit is 6000)
            if total_chars + len(q_title) + len(a_val) > 5800:
                embed.add_field(name="⚠️ Application Truncated", value="*Click 'View Full App' to read the rest.*", inline=False)
                break
                
            embed.add_field(name=q_title, value=a_val, inline=False)
            total_chars += len(q_title) + len(a_val)
            
        embed.set_footer(text=f"Pending Queue: {self.current_idx + 1} of {len(self.submissions)} | Status: {sub.status.upper()}")
        return embed

    async def process_decision(self, interaction: discord.Interaction, status: str, action_message: str):
        sub, template, app = self.submissions.pop(self.current_idx)
        await DatabaseController.update_submission_status(sub.id, status)
        
        if self.current_idx >= len(self.submissions):
            self.current_idx = max(0, len(self.submissions) - 1)
        
        if not self.submissions:
            embed = discord.Embed(title="✅ Inbox Zero", description="There are no more pending applications to review!", color=discord.Color.green())
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            self.update_buttons()
            await interaction.response.edit_message(embed=await self.generate_embed(), view=self)
            
        await interaction.followup.send(f"{action_message} application for **{app.username}**.", ephemeral=True)

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

    @discord.ui.button(label="📄 View Full App", style=discord.ButtonStyle.primary, row=0)
    async def full_app_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub, template, app = self.submissions[self.current_idx]
        answers = await DatabaseController.get_submission_answers(sub.id)
        
        content = f"--- APPLICATION: {template.name} ---\n"
        content += f"Applicant: {app.username} (ID: {app.user_id})\n"
        content += f"Preferred Name: {app.preferred_name}\n"
        content += f"Pronouns: {app.pronouns}\n"
        content += f"Submitted: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(sub.submitted_at))} UTC\n"
        content += f"Status: {sub.status.upper()}\n"
        content += "-" * 50 + "\n\n"
        
        for i, (q_text, a_text) in enumerate(answers):
            content += f"Q{i+1}: {q_text}\n"
            content += f"A: {a_text}\n\n"
            
        file = discord.File(fp=io.BytesIO(content.encode('utf-8')), filename=f"{app.username}_App.txt")
        await interaction.response.send_message(content=f"Here is the full application for **{app.username}**:", file=file, ephemeral=True)

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, row=1)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_decision(interaction, "confirmed", "✅ Approved")

    @discord.ui.button(label="⏳ Leave Pending", style=discord.ButtonStyle.secondary, row=1)
    async def pending_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub = self.submissions.pop(self.current_idx)
        self.submissions.append(sub)
        if self.current_idx >= len(self.submissions):
            self.current_idx = 0
            
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)
        await interaction.followup.send("⏳ Skipped and sent to back of Pending queue.", ephemeral=True)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, row=1)
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_decision(interaction, "denied", "❌ Denied")


class HistoryPaginationView(discord.ui.View):
    def __init__(self, submissions, guild_id: str):
        super().__init__(timeout=900)
        self.submissions = submissions 
        self.current_idx = 0
        self.guild_id = guild_id
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_idx == 0
        self.next_btn.disabled = self.current_idx == len(self.submissions) - 1

    async def generate_embed(self):
        sub, template, app = self.submissions[self.current_idx]
        color = discord.Color.green() if sub.status == "confirmed" else discord.Color.red()
        
        embed = discord.Embed(
            title=f"🏛️ History: {template.name}", 
            description=f"**Applicant:** <@{app.user_id}> ({app.username})\n**Pref Name:** {app.preferred_name}\n**Pronouns:** {app.pronouns}\n**Date:** <t:{sub.submitted_at}:F>",
            color=color
        )
        
        answers = await DatabaseController.get_submission_answers(sub.id)
        
        total_chars = len(embed.title) + len(embed.description)
        for q_text, a_text in answers:
            q_title = q_text[:250]
            a_val = a_text or "*No answer*"
            
            if len(a_val) > 800:
                a_val = a_val[:797] + "..."
                
            if total_chars + len(q_title) + len(a_val) > 5800:
                embed.add_field(name="⚠️ Application Truncated", value="*Click 'View Full App' to read the rest.*", inline=False)
                break
                
            embed.add_field(name=q_title, value=a_val, inline=False)
            total_chars += len(q_title) + len(a_val)
            
        embed.set_footer(text=f"History Record {self.current_idx + 1} of {len(self.submissions)} | Status: {sub.status.upper()}")
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

    @discord.ui.button(label="📄 View Full App", style=discord.ButtonStyle.primary, row=0)
    async def full_app_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub, template, app = self.submissions[self.current_idx]
        answers = await DatabaseController.get_submission_answers(sub.id)
        
        content = f"--- APPLICATION: {template.name} ---\n"
        content += f"Applicant: {app.username} (ID: {app.user_id})\n"
        content += f"Preferred Name: {app.preferred_name}\n"
        content += f"Pronouns: {app.pronouns}\n"
        content += f"Submitted: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(sub.submitted_at))} UTC\n"
        content += f"Status: {sub.status.upper()}\n"
        content += "-" * 50 + "\n\n"
        
        for i, (q_text, a_text) in enumerate(answers):
            content += f"Q{i+1}: {q_text}\n"
            content += f"A: {a_text}\n\n"
            
        file = discord.File(fp=io.BytesIO(content.encode('utf-8')), filename=f"{app.username}_App.txt")
        await interaction.response.send_message(content=f"Here is the full application for **{app.username}**:", file=file, ephemeral=True)

    @discord.ui.button(label="⏪ Undo (Send to Pending)", style=discord.ButtonStyle.danger, row=1)
    async def revert_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub, template, app = self.submissions.pop(self.current_idx)
        await DatabaseController.update_submission_status(sub.id, "pending")
        
        if self.current_idx >= len(self.submissions):
            self.current_idx = max(0, len(self.submissions) - 1)
            
        if not self.submissions:
            embed = discord.Embed(title="History Empty", description="There are no more historical applications to view.", color=discord.Color.blurple())
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            self.update_buttons()
            await interaction.response.edit_message(embed=await self.generate_embed(), view=self)
            
        await interaction.followup.send(f"⏪ Application for **{app.username}** has been sent back to the `/forms review` queue.", ephemeral=True)

# ==========================================
#          ADMIN MANAGEMENT UI
# ==========================================

class CreateFormModal(discord.ui.Modal, title="Create New Form"):
    name = discord.ui.TextInput(label="Form Name", placeholder="e.g. Officer Application", required=True)
    desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)
    cooldown = discord.ui.TextInput(label="Cooldown (Days)", placeholder="0 for no cooldown", default="0", required=False)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cooldown_val = int(self.cooldown.value.strip() or "0")
        except ValueError:
            return await interaction.response.send_message("❌ Cooldown must be a valid number of days.", ephemeral=True)

        await DatabaseController.create_form(self.parent_view.guild_id, self.name.value, self.desc.value, cooldown_val)
        await self.parent_view.refresh(interaction)

class EditDetailsModal(discord.ui.Modal, title="Edit Form Details"):
    name = discord.ui.TextInput(label="Form Name", required=True)
    desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)
    cooldown = discord.ui.TextInput(label="Cooldown (Days)", placeholder="0 for no cooldown", required=True)

    def __init__(self, form, parent_view):
        super().__init__()
        self.form = form
        self.parent_view = parent_view
        
        self.name.default = form.name
        self.desc.default = form.description
        self.cooldown.default = str(form.cooldown_days)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cd = int(self.cooldown.value.strip() or "0")
        except ValueError:
            return await interaction.response.send_message("❌ Cooldown must be a valid number.", ephemeral=True)
            
        await DatabaseController.update_form_details(self.form.id, self.name.value, self.desc.value, cd)
        self.form.name = self.name.value
        self.form.description = self.desc.value
        self.form.cooldown_days = cd
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

class EditQuestionModal(discord.ui.Modal, title="Edit Question"):
    q_text = discord.ui.TextInput(label="Question Text", style=discord.TextStyle.paragraph, required=True)
    q_type = discord.ui.TextInput(label="Type (text, single, or multiple)", required=True, placeholder="Enter: text, single, or multiple")
    options = discord.ui.TextInput(label="Options (Comma separated)", required=False, placeholder="Leave blank if type is text")

    def __init__(self, question, parent_view):
        super().__init__()
        self.question = question
        self.parent_view = parent_view
        
        self.q_text.default = question.question_text
        self.q_type.default = question.question_type
        self.options.default = question.options if question.options else ""

    async def on_submit(self, interaction: discord.Interaction):
        new_type = self.q_type.value.strip().lower()
        if new_type not in ["text", "single", "multiple"]:
            return await interaction.response.send_message("❌ Type must be exactly 'text', 'single', or 'multiple'.", ephemeral=True)
        
        opts = self.options.value if new_type in ["single", "multiple"] else None
        
        await DatabaseController.update_form_question(self.question.id, self.q_text.value, new_type, opts)
        await self.parent_view.parent_form_view.refresh(interaction)

class EditQuestionView(discord.ui.View):
    def __init__(self, question, parent_form_view):
        super().__init__(timeout=600)
        self.question = question
        self.parent_form_view = parent_form_view

    async def generate_embed(self):
        embed = discord.Embed(title="⚙️ Editing Question", color=discord.Color.blue())
        embed.add_field(name="Question Text", value=self.question.question_text, inline=False)
        embed.add_field(name="Type", value=self.question.question_type.upper(), inline=True)
        if self.question.options:
            embed.add_field(name="Options", value=self.question.options, inline=False)
        return embed

    @discord.ui.button(label="✏️ Edit Content / Type", style=discord.ButtonStyle.primary, row=0)
    async def edit_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await interaction.response.send_modal(EditQuestionModal(self.question, self))

    @discord.ui.button(label="🗑️ Delete Question", style=discord.ButtonStyle.danger, row=0)
    async def delete_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await DatabaseController.delete_form_question(self.question.id)
        await self.parent_form_view.refresh(interaction)

    @discord.ui.button(label="⬅️ Back to Form", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await self.parent_form_view.refresh(interaction)


class EditFormView(discord.ui.View):
    def __init__(self, guild_id: str, form, main_view):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.form = form
        self.main_view = main_view

    async def refresh(self, interaction: discord.Interaction):
        self.clear_items()
        questions = await DatabaseController.get_form_questions(self.form.id)
        
        cooldown_str = f"{self.form.cooldown_days} Days" if self.form.cooldown_days > 0 else "None"
        embed = discord.Embed(
            title=f"🛠️ Managing: {self.form.name}", 
            description=f"**Cooldown:** {cooldown_str}\n\n**Description:** {self.form.description}", 
            color=discord.Color.orange()
        )
        
        q_list = ""
        for i, q in enumerate(questions):
            type_lbl = "[TEXT]" if q.question_type == 'text' else f"[{q.question_type.upper()}]"
            q_list += f"**{i+1}.** {type_lbl} {q.question_text}\n"
        
        if not q_list:
            q_list = "*No questions added yet.*"
        
        embed.add_field(name="Current Questions", value=q_list[:1024])
        
        if questions:
            options = [discord.SelectOption(label=f"Q{i+1}: {q.question_text[:50]}", value=str(q.id)) for i, q in enumerate(questions[:25])]
            select = discord.ui.Select(placeholder="Select a question to edit or delete...", options=options, row=0)
            
            async def select_callback(inter: discord.Interaction):
                q_id = int(select.values[0])
                question = await DatabaseController.get_form_question_by_id(q_id)
                q_view = EditQuestionView(question, self)
                await inter.response.edit_message(embed=await q_view.generate_embed(), view=q_view)
                
            select.callback = select_callback
            self.add_item(select)

        self.add_item(discord.ui.Button(label="✏️ Edit Details", style=discord.ButtonStyle.primary, row=1, custom_id="edit_details"))
        self.add_item(discord.ui.Button(label="Add Text Q", style=discord.ButtonStyle.secondary, row=2, custom_id="add_text"))
        self.add_item(discord.ui.Button(label="Add Single Choice Q", style=discord.ButtonStyle.secondary, row=2, custom_id="add_single"))
        self.add_item(discord.ui.Button(label="Add Multi Choice Q", style=discord.ButtonStyle.secondary, row=2, custom_id="add_multi"))
        self.add_item(discord.ui.Button(label="🗑️ Delete Form", style=discord.ButtonStyle.danger, row=3, custom_id="del_form"))
        self.add_item(discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=3, custom_id="back_btn"))
        
        for child in self.children:
            if getattr(child, "custom_id", None) == "edit_details": child.callback = self.edit_details
            elif getattr(child, "custom_id", None) == "add_text": child.callback = self.add_text
            elif getattr(child, "custom_id", None) == "add_single": child.callback = self.add_single
            elif getattr(child, "custom_id", None) == "add_multi": child.callback = self.add_multi
            elif getattr(child, "custom_id", None) == "del_form": child.callback = self.del_form
            elif getattr(child, "custom_id", None) == "back_btn": child.callback = self.back_btn

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def edit_details(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditDetailsModal(self.form, self))

    async def add_text(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddQuestionModal(self.form.id, "text", self))

    async def add_single(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddQuestionModal(self.form.id, "single", self))

    async def add_multi(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddQuestionModal(self.form.id, "multiple", self))

    async def del_form(self, interaction: discord.Interaction):
        await DatabaseController.delete_form(self.form.id)
        await self.main_view.refresh(interaction)

    async def back_btn(self, interaction: discord.Interaction):
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

    @app_commands.command(name="setrole", description="Set the role allowed to manage and review forms.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setrole(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_forms_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ Form management access granted to {role.mention}.", ephemeral=True)

    @app_commands.command(name="apply", description="Start an application/form.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    async def apply_form(self, interaction: discord.Interaction, form_name: str):
        guild_id = str(interaction.guild_id)
        
        form = await DatabaseController.get_form_by_name(guild_id, form_name)
        if not form:
            return await interaction.response.send_message(f"❌ Form **{form_name}** not found.", ephemeral=True)

        applicant = await DatabaseController.get_applicant(guild_id, str(interaction.user.id))
        if applicant:
            if form.cooldown_days > 0:
                has_recent = await DatabaseController.check_recent_submission(form.id, applicant.id, form.cooldown_days)
                if has_recent:
                    return await interaction.response.send_message(f"❌ You have already submitted an application to this form within the last {form.cooldown_days} days. Please try again later.", ephemeral=True)
            
            await start_form_session(interaction, form.id, form.name, applicant)
        else:
            await interaction.response.send_modal(ApplicantSetupModal(form.id, form.name))

    @app_commands.command(name="manage", description="Interactive UI to manage, create, and edit forms.")
    async def manage_forms(self, interaction: discord.Interaction):
        if not await has_form_perms(interaction):
            return await interaction.response.send_message("❌ You lack the required Forms Role or Manage Server permissions.", ephemeral=True)
            
        view = ManageFormsView(str(interaction.guild_id))
        embed = discord.Embed(title="Loading...", color=discord.Color.purple())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.refresh(interaction)

    @app_commands.command(name="review", description="Review pending form applications.")
    async def review_forms(self, interaction: discord.Interaction):
        if not await has_form_perms(interaction):
            return await interaction.response.send_message("❌ You lack the required Forms Role or Manage Server permissions.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        submissions = await DatabaseController.get_pending_submissions(str(interaction.guild_id))
        
        if not submissions:
            return await interaction.followup.send("✅ There are no pending applications to review!")
            
        view = ReviewPaginationView(submissions, str(interaction.guild_id))
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="history", description="Review historical (approved/denied) form applications.")
    async def history_forms(self, interaction: discord.Interaction):
        if not await has_form_perms(interaction):
            return await interaction.response.send_message("❌ You lack the required Forms Role or Manage Server permissions.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        submissions = await DatabaseController.get_historical_submissions(str(interaction.guild_id))
        
        if not submissions:
            return await interaction.followup.send("🔍 There are no historical applications yet.")
            
        view = HistoryPaginationView(submissions, str(interaction.guild_id))
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    # --- CLI BACKUP COMMANDS ---
    @app_commands.command(name="backup_create", description="CLI Backup: Create a form.")
    async def cmd_create(self, interaction: discord.Interaction, name: str, description: str, cooldown_days: int = 0):
        if not await has_form_perms(interaction):
            return await interaction.response.send_message("❌ You lack the required Forms Role or Manage Server permissions.", ephemeral=True)
            
        await DatabaseController.create_form(str(interaction.guild_id), name, description, cooldown_days)
        await interaction.response.send_message(f"✅ Created form: **{name}** (Cooldown: {cooldown_days} days)", ephemeral=True)

    @app_commands.command(name="backup_add_question", description="CLI Backup: Add a question to a form.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    @app_commands.choices(q_type=[
        app_commands.Choice(name="Text (Paragraph)", value="text"),
        app_commands.Choice(name="Single Choice", value="single"),
        app_commands.Choice(name="Multiple Choice", value="multiple"),
    ])
    async def cmd_add_q(self, interaction: discord.Interaction, form_name: str, q_type: app_commands.Choice[str], text: str, options: str = None):
        if not await has_form_perms(interaction):
            return await interaction.response.send_message("❌ You lack the required Forms Role or Manage Server permissions.", ephemeral=True)
            
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if not form:
            return await interaction.response.send_message("❌ Form not found.", ephemeral=True)
        
        await DatabaseController.add_form_question(form.id, text, q_type.value, options)
        await interaction.response.send_message(f"✅ Question added to **{form_name}**.", ephemeral=True)

    @app_commands.command(name="backup_delete", description="CLI Backup: Delete a form.")
    @app_commands.autocomplete(form_name=form_autocomplete)
    async def cmd_delete(self, interaction: discord.Interaction, form_name: str):
        if not await has_form_perms(interaction):
            return await interaction.response.send_message("❌ You lack the required Forms Role or Manage Server permissions.", ephemeral=True)
            
        form = await DatabaseController.get_form_by_name(str(interaction.guild_id), form_name)
        if form:
            await DatabaseController.delete_form(form.id)
            await interaction.response.send_message(f"🗑️ Deleted form **{form_name}**.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Form not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FormsCog(bot))