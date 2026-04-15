import os
import time
from typing import Optional
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, select, or_, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from models import (
    ServerConfig, Aid, Committee, CommitteeAssignment, QuoteTemplate, Ticket, 
    TicketStaffRole, Profile, Skill, ProfileSkill, Event, EventAttendance,
    Applicant, FormTemplate, FormQuestion, FormSubmission, FormAnswer
)

DB_PATH = "./data/mutual_aid.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.lstrip('./')}"

engine = create_async_engine(DATABASE_URL, echo=False)

class DatabaseController:
    @staticmethod
    async def setup():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    @staticmethod
    async def add_quote_template(name: str, file_path: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(QuoteTemplate, name)
            if obj:
                obj.file_path = file_path
            else:
                obj = QuoteTemplate(name=name, file_path=file_path)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_quote_template(name: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(QuoteTemplate, name)
            return obj.file_path if obj else None

    @staticmethod
    async def get_all_quote_templates():
        async with AsyncSession(engine) as session:
            stmt = select(QuoteTemplate).order_by(QuoteTemplate.name.asc())
            result = await session.execute(stmt)
            return [(obj.name,) for obj in result.scalars().all()]

    @staticmethod
    async def delete_quote_template(name: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(QuoteTemplate, name)
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def set_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.role_id if obj else None

    @staticmethod
    async def create_aid(guild_id: str, channel_id: str, user_id: str, amount: float, description: str):
        now = int(time.time())
        next_reminder = now + 86400
        obj = Aid(guild_id=guild_id, channel_id=channel_id, user_id=user_id, amount_requested=amount, reason=description, created_at=now, next_reminder_at=next_reminder)
        async with AsyncSession(engine) as session:
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def get_active_aid(aid_id: int, guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.id == aid_id,
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return (obj.amount_requested, obj.amount_received, obj.user_id)
            return None

    @staticmethod
    async def update_aid_progress(aid_id: int, new_total: float, status: str = 'active'):
        async with AsyncSession(engine) as session:
            obj = await session.get(Aid, aid_id)
            if obj:
                obj.amount_received = new_total
                obj.status = status
                await session.commit()

    @staticmethod
    async def get_all_active(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            return [(obj.id, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason) for obj in result.scalars().all()]

    @staticmethod
    async def delete_aid(aid_id: int, guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.id == aid_id,
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return False
            obj.status = 'deleted'
            await session.commit()
            return True

    @staticmethod
    async def clear_all(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                obj.status = 'deleted'
            await session.commit()

    @staticmethod
    async def get_due_reminders():
        async with AsyncSession(engine) as session:
            now = int(time.time())
            stmt = select(Aid).where(
                Aid.status == 'active',
                Aid.next_reminder_at <= now,
                Aid.channel_id != None
            )
            result = await session.execute(stmt)
            return [(obj.id, obj.guild_id, obj.channel_id, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason) for obj in result.scalars().all()]

    @staticmethod
    async def reset_reminder(aid_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(Aid, aid_id)
            if obj:
                obj.next_reminder_at = int(time.time()) + 172800
                await session.commit()

    @staticmethod
    async def get_aid_by_id(aid_id: int, guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.id == aid_id,
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return (obj.id, obj.guild_id, obj.channel_id, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason)
            return None

    @staticmethod
    async def setup_indexes():
        pass

    @staticmethod
    async def create_committee(guild_id: str, name: str, description: str = "No description provided."):
        async with AsyncSession(engine) as session:
            obj = Committee(guild_id=guild_id, name=name, description=description)
            session.add(obj)
            try:
                await session.commit()
                await session.refresh(obj)
                return obj.id
            except IntegrityError:
                return None

    @staticmethod
    async def get_all_committees(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(Committee.guild_id == guild_id)
            result = await session.execute(stmt)
            return [(obj.id, obj.name, obj.description) for obj in result.scalars().all()]

    @staticmethod
    async def get_committee_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(
                Committee.guild_id == guild_id,
                func.lower(Committee.name) == name.lower()
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return (obj.id, obj.name)
            return None

    @staticmethod
    async def get_user_committee_roles(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee.name, CommitteeAssignment.role_type).select_from(CommitteeAssignment).outerjoin(
                Committee, CommitteeAssignment.committee_id == Committee.id
            ).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.user_id == user_id
            )
            result = await session.execute(stmt)
            return [(row[0] if row[0] is not None else 'Global', row[1]) for row in result.all()]

    @staticmethod
    async def assign_committee_role(guild_id: str, user_id: str, committee_id: int, role_type: str):
        async with AsyncSession(engine) as session:
            obj = CommitteeAssignment(guild_id=guild_id, user_id=user_id, committee_id=committee_id, role_type=role_type)
            session.add(obj)
            try:
                await session.commit()
            except IntegrityError:
                pass

    @staticmethod
    async def get_committee_members(guild_id: str, committee_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.committee_id == committee_id
            )
            result = await session.execute(stmt)
            return [(obj.user_id, obj.role_type) for obj in result.scalars().all()]

    @staticmethod
    async def update_committee_name(guild_id: str, committee_id: int, new_name: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(Committee.id == committee_id, Committee.guild_id == guild_id)
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                obj.name = new_name
                await session.commit()

    @staticmethod
    async def delete_committee(guild_id: str, committee_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(Committee.id == committee_id, Committee.guild_id == guild_id)
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def remove_assignment(guild_id: str, user_id: str, committee_id: Optional[int], role_type: str):
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.user_id == user_id,
                CommitteeAssignment.role_type == role_type
            )
            if committee_id:
                stmt = stmt.where(CommitteeAssignment.committee_id == committee_id)
            else:
                stmt = stmt.where(CommitteeAssignment.committee_id == None)
                
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                await session.delete(obj)
            await session.commit()

    @staticmethod
    async def get_all_org_members(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment.user_id, CommitteeAssignment.role_type, Committee.name).select_from(CommitteeAssignment).outerjoin(
                Committee, CommitteeAssignment.committee_id == Committee.id
            ).where(CommitteeAssignment.guild_id == guild_id)
            result = await session.execute(stmt)
            return [(row[0], row[1], row[2] if row[2] is not None else 'Global') for row in result.all()]

    @staticmethod
    async def create_ticket(ticket_id: str, guild_id: str, user_id: str, channel_id: str):
        async with AsyncSession(engine) as session:
            obj = Ticket(ticket_id=ticket_id, guild_id=guild_id, user_id=user_id, channel_id=channel_id, created_at=int(time.time()))
            session.add(obj)
            await session.commit()

    @staticmethod
    async def close_ticket_db(channel_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Ticket).where(Ticket.channel_id == channel_id)
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                obj.status = "closed"
            await session.commit()

    @staticmethod
    async def close_all_active_tickets_db(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Ticket).where(Ticket.guild_id == guild_id, Ticket.status == "active")
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                obj.status = "closed"
            await session.commit()

    @staticmethod
    async def add_staff_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = TicketStaffRole(guild_id=guild_id, role_id=role_id)
            session.add(obj)
            try:
                await session.commit()
            except IntegrityError:
                pass

    @staticmethod
    async def remove_staff_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(TicketStaffRole, (guild_id, role_id))
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_staff_roles(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(TicketStaffRole).where(TicketStaffRole.guild_id == guild_id)
            result = await session.execute(stmt)
            return [obj.role_id for obj in result.scalars().all()]

    @staticmethod
    async def set_crp_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.crp_role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, crp_role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_crp_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.crp_role_id if obj else None

    @staticmethod
    async def is_crp_member(guild_id: str, user_id: str) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.user_id == user_id
            ).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def create_skill(guild_id: str, name: str, description: str, is_wanted: bool) -> bool:
        async with AsyncSession(engine) as session:
            obj = Skill(guild_id=guild_id, name=name.strip(), description=description, is_wanted=1 if is_wanted else 0)
            session.add(obj)
            try:
                await session.commit()
                return True
            except IntegrityError:
                return False

    @staticmethod
    async def delete_skill(guild_id: str, name: str) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(Skill).where(Skill.guild_id == guild_id, func.lower(Skill.name) == name.lower())
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return False
            stmt2 = select(ProfileSkill).where(ProfileSkill.guild_id == guild_id, ProfileSkill.skill_id == obj.id)
            result2 = await session.execute(stmt2)
            for ps in result2.scalars().all():
                await session.delete(ps)
            await session.delete(obj)
            await session.commit()
            return True

    @staticmethod
    async def get_all_server_skills(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Skill).where(Skill.guild_id == guild_id).order_by(Skill.is_wanted.desc(), Skill.name.asc())
            result = await session.execute(stmt)
            return [(obj.id, obj.name, obj.description, obj.is_wanted) for obj in result.scalars().all()]

    @staticmethod
    async def set_profile_skill(guild_id: str, user_id: str, skill_id: int, proficiency: str):
        async with AsyncSession(engine) as session:
            prof = await session.get(Profile, (guild_id, user_id))
            if not prof:
                session.add(Profile(guild_id=guild_id, user_id=user_id))
                try:
                    await session.commit()
                except IntegrityError:
                    pass
            ps = await session.get(ProfileSkill, (guild_id, user_id, skill_id))
            if ps:
                ps.proficiency = proficiency
            else:
                session.add(ProfileSkill(guild_id=guild_id, user_id=user_id, skill_id=skill_id, proficiency=proficiency))
            await session.commit()

    @staticmethod
    async def remove_profile_skill(guild_id: str, user_id: str, skill_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(ProfileSkill, (guild_id, user_id, skill_id))
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_user_skills(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Skill.name, ProfileSkill.proficiency).select_from(ProfileSkill).join(
                Skill, ProfileSkill.skill_id == Skill.id
            ).where(
                ProfileSkill.guild_id == guild_id,
                ProfileSkill.user_id == user_id
            ).order_by(Skill.name.asc())
            result = await session.execute(stmt)
            return [(row[0], row[1]) for row in result.all()]

    @staticmethod
    async def get_users_by_skill(guild_id: str, skill_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(ProfileSkill).where(
                ProfileSkill.guild_id == guild_id,
                ProfileSkill.skill_id == skill_id
            )
            result = await session.execute(stmt)
            return [(obj.user_id, obj.proficiency) for obj in result.scalars().all()]

    @staticmethod
    async def edit_skill(guild_id: str, name: str, description: str, is_wanted: bool) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(Skill).where(Skill.guild_id == guild_id, func.lower(Skill.name) == name.lower())
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                obj.description = description
                obj.is_wanted = 1 if is_wanted else 0
                await session.commit()
                return True
            return False

    @staticmethod
    async def get_skill_tree(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Skill.name, Skill.is_wanted, ProfileSkill.user_id, ProfileSkill.proficiency).select_from(Skill).outerjoin(
                ProfileSkill, Skill.id == ProfileSkill.skill_id
            ).where(Skill.guild_id == guild_id).order_by(Skill.is_wanted.desc(), Skill.name.asc(), ProfileSkill.proficiency.desc())
            result = await session.execute(stmt)
            return [(row[0], row[1], row[2], row[3]) for row in result.all()]

    @staticmethod
    async def update_skill_by_id(guild_id: str, skill_id: int, new_name: str, new_desc: str, is_wanted: bool) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(Skill, skill_id)
            if obj and obj.guild_id == guild_id:
                obj.name = new_name.strip()
                obj.description = new_desc
                obj.is_wanted = 1 if is_wanted else 0
                try:
                    await session.commit()
                    return True
                except IntegrityError:
                    return False
            return False

    @staticmethod
    async def delete_skill_by_id(guild_id: str, skill_id: int) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(Skill, skill_id)
            if obj and obj.guild_id == guild_id:
                stmt = select(ProfileSkill).where(ProfileSkill.guild_id == guild_id, ProfileSkill.skill_id == skill_id)
                result = await session.execute(stmt)
                for ps in result.scalars().all():
                    await session.delete(ps)
                await session.delete(obj)
                await session.commit()
                return True
            return False

    
    @staticmethod
    async def get_or_create_event(guild_id: str, name: str) -> int:
        async with AsyncSession(engine) as session:
            stmt = select(Event).where(
                Event.guild_id == guild_id,
                func.lower(Event.name) == name.lower()
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return obj.id
            
            now = int(time.time())
            obj = Event(guild_id=guild_id, name=name, created_at=now)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def log_attendance(event_id: int, user_ids: list[str]) -> int:
        added_count = 0
        async with AsyncSession(engine) as session:
            now = int(time.time())
            for uid in user_ids:
                obj = EventAttendance(event_id=event_id, user_id=uid, check_in_time=now)
                session.add(obj)
                try:
                    await session.commit()
                    added_count += 1
                except IntegrityError:
                    # Ignore if the user is already logged for this event
                    await session.rollback()
        return added_count


    @staticmethod
    async def get_applicant(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Applicant).where(
                Applicant.guild_id == guild_id, 
                Applicant.user_id == user_id
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def create_applicant(guild_id: str, user_id: str, username: str, preferred_name: str, pronouns: str):
        async with AsyncSession(engine) as session:
            obj = Applicant(
                guild_id=guild_id, user_id=user_id, username=username, 
                preferred_name=preferred_name, pronouns=pronouns
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    @staticmethod
    async def get_all_forms(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormTemplate).where(FormTemplate.guild_id == guild_id)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_form_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormTemplate).where(
                FormTemplate.guild_id == guild_id,
                func.lower(FormTemplate.name) == name.lower()
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def get_form_by_id(form_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(FormTemplate, form_id)

    @staticmethod
    async def delete_form(form_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormTemplate, form_id)
            if obj:
                # Manual cascading for sqlite safety
                q_stmt = select(FormQuestion).where(FormQuestion.form_id == form_id)
                questions = await session.execute(q_stmt)
                for q in questions.scalars().all():
                    await session.delete(q)
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def add_form_question(form_id: int, text: str, q_type: str, options: str = None):
        async with AsyncSession(engine) as session:
            obj = FormQuestion(form_id=form_id, question_text=text, question_type=q_type, options=options)
            session.add(obj)
            await session.commit()

    @staticmethod
    async def delete_form_question(question_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormQuestion, question_id)
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_form_questions(form_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(FormQuestion).where(FormQuestion.form_id == form_id).order_by(FormQuestion.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()


    @staticmethod
    async def save_form_submission(form_id: int, applicant_id: int, answers: dict) -> int:
        async with AsyncSession(engine) as session:
            submission = FormSubmission(
                form_id=form_id, 
                applicant_id=applicant_id, 
                submitted_at=int(time.time()), 
                status="pending"
            )
            session.add(submission)
            await session.flush() # Flushes to generate the ID without closing the transaction
            sub_id = submission.id
            
            for q_id, ans_text in answers.items():
                ans_obj = FormAnswer(
                    submission_id=sub_id,
                    question_id=q_id,
                    answer_text=ans_text
                )
                session.add(ans_obj)
                
            await session.commit()
            return sub_id

    @staticmethod
    async def get_pending_submissions(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormSubmission, FormTemplate, Applicant).join(
                FormTemplate, FormSubmission.form_id == FormTemplate.id
            ).join(
                Applicant, FormSubmission.applicant_id == Applicant.id
            ).where(
                FormTemplate.guild_id == guild_id,
                FormSubmission.status == "pending"
            ).order_by(FormSubmission.submitted_at.asc())
            result = await session.execute(stmt)
            return result.all()

    @staticmethod
    async def get_submission_answers(submission_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(FormQuestion.question_text, FormAnswer.answer_text).join(
                FormAnswer, FormQuestion.id == FormAnswer.question_id
            ).where(FormAnswer.submission_id == submission_id).order_by(FormQuestion.id.asc())
            result = await session.execute(stmt)
            return result.all()

    @staticmethod
    async def update_submission_status(submission_id: int, status: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormSubmission, submission_id)
            if obj:
                obj.status = status
                await session.commit()


    @staticmethod
    async def create_form(guild_id: str, name: str, description: str, cooldown_days: int = 0):
        async with AsyncSession(engine) as session:
            obj = FormTemplate(
                guild_id=guild_id, name=name, description=description, 
                created_at=int(time.time()), cooldown_days=cooldown_days
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def check_recent_submission(form_id: int, applicant_id: int, cooldown_days: int) -> bool:
        if cooldown_days <= 0:
            return False # No cooldown configured
            
        async with AsyncSession(engine) as session:
            cutoff_time = int(time.time()) - (cooldown_days * 24 * 60 * 60)
            stmt = select(FormSubmission).where(
                FormSubmission.form_id == form_id,
                FormSubmission.applicant_id == applicant_id,
                FormSubmission.submitted_at >= cutoff_time
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def update_form_details(form_id: int, name: str, description: str, cooldown_days: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormTemplate, form_id)
            if obj:
                obj.name = name
                obj.description = description
                obj.cooldown_days = cooldown_days
                await session.commit()

    @staticmethod
    async def get_form_question_by_id(question_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(FormQuestion, question_id)

    @staticmethod
    async def update_form_question(question_id: int, text: str, q_type: str, options: str = None):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormQuestion, question_id)
            if obj:
                obj.question_text = text
                obj.question_type = q_type
                obj.options = options
                await session.commit()

    @staticmethod
    async def set_forms_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.forms_role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, forms_role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_forms_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.forms_role_id if obj else None

    @staticmethod
    async def get_historical_submissions(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormSubmission, FormTemplate, Applicant).join(
                FormTemplate, FormSubmission.form_id == FormTemplate.id
            ).join(
                Applicant, FormSubmission.applicant_id == Applicant.id
            ).where(
                FormTemplate.guild_id == guild_id,
                FormSubmission.status != "pending"
            ).order_by(FormSubmission.submitted_at.desc()) # Newest history first
            result = await session.execute(stmt)
            return result.all()