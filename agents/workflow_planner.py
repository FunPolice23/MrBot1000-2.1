from dataclasses import dataclass, field
from typing import List

from earning_pipeline import Opportunity


@dataclass
class WorkflowStep:
    action: str
    title: str
    notes: str


@dataclass
class WorkflowPlan:
    platform: str
    steps: List[WorkflowStep] = field(default_factory=list)


class WorkflowPlanner:
    """Turn an opportunity into a practical execution plan."""

    def __init__(self):
        self.platform_templates = {
            "upwork": [
                WorkflowStep("apply", "Apply to the job", "Submit a tailored proposal that highlights Python automation experience and delivery confidence."),
                WorkflowStep("deliver", "Deliver the work", "Create the required deliverables and confirm scope before sending final output."),
                WorkflowStep("submit", "Submit the work", "Send the completed deliverables through the platform’s submission flow and request payment confirmation."),
            ],
            "fiverr": [
                WorkflowStep("apply", "Create a relevant gig offer", "Prepare a focused offer, include a concise scope, and respond to the client request."),
                WorkflowStep("deliver", "Complete the requested work", "Deliver the work in the agreed format and keep the client updated."),
                WorkflowStep("submit", "Send the final delivery", "Submit the finished work and ask for approval or payment release."),
            ],
            "reddit": [
                WorkflowStep("research", "Research the offer", "Verify the posting details, payment terms, and any reputation cues before replying."),
                WorkflowStep("contact", "Make contact", "Reply with a short, professional pitch and clarify the scope."),
                WorkflowStep("submit", "Complete the payout handoff", "Once approved, deliver the result and collect payment through the agreed method."),
            ],
            "github": [
                WorkflowStep("research", "Review the issue", "Read the task, requirements, and acceptance criteria before coding."),
                WorkflowStep("implement", "Implement the fix", "Make the smallest safe change that satisfies the issue."),
                WorkflowStep("submit", "Open or update the submission", "Submit the patch or PR and follow up on bounty or payment status."),
            ],
        }

    def build_plan(self, opportunity: Opportunity) -> WorkflowPlan:
        platform_key = (opportunity.platform or "").lower()
        for key, steps in self.platform_templates.items():
            if key in platform_key:
                return WorkflowPlan(platform=platform_key, steps=list(steps))

        return WorkflowPlan(
            platform=platform_key,
            steps=[
                WorkflowStep("research", "Research the opportunity", "Investigate the posting, requirements, and payment details before engagement."),
                WorkflowStep("contact", "Reach out or apply", "Use the platform’s application or contact method to introduce yourself and clarify next steps."),
                WorkflowStep("manual_followup", "Follow up manually", "If the platform blocks automation, continue manually through the site or message thread until the job is accepted and paid."),
            ],
        )
