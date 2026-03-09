"""Regulatory & legal entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Regulatory(Entity):
    """Immutable regulatory entity representing compliance obligations.

    Extends Entity with regulatory requirements, legal mandates, and
    compliance obligations relevant to emergency medicine practice.
    """

    reg_id: str = ""
    name: str = ""
    regulation_type: str = ""  # federal, state, institutional, accreditation
    category: str = (
        ""  # emtala, consent, restraint, reporting, documentation, hipaa, controlled_substance
    )
    description: str = ""
    requirements: tuple[str, ...] = ()
    documentation_elements: tuple[str, ...] = ()
    violations_consequences: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    active: bool = True


# --- Bundled regulatory data ---

_BUNDLED_REGULATIONS: dict[str, dict[str, Any]] = {
    "EMTALA_MSE": {
        "reg_id": "REG-EMTALA-001",
        "name": "EMTALA - Medical Screening Examination",
        "regulation_type": "federal",
        "category": "emtala",
        "description": (
            "Under the Emergency Medical Treatment and Labor Act, any individual "
            "who presents to an emergency department requesting examination or "
            "treatment must receive an appropriate medical screening examination "
            "to determine whether an emergency medical condition exists, regardless "
            "of ability to pay."
        ),
        "requirements": (
            "Provide MSE to any individual who presents and requests examination",
            "MSE must be performed by a qualified medical person",
            "MSE must be within the capability of the hospital's emergency department",
            "MSE must not be delayed to inquire about payment or insurance status",
            "MSE must be equivalent regardless of patient's ability to pay",
            "Hospital must maintain an on-call list of physicians for emergency coverage",
            "Central log of all individuals presenting for emergency care must be maintained",
        ),
        "documentation_elements": (
            "Time of patient arrival",
            "Time MSE initiated",
            "Qualified medical person performing MSE",
            "Findings of MSE",
            "Determination of whether emergency medical condition exists",
            "Central log entry with presenting complaint and disposition",
        ),
        "violations_consequences": (
            "Civil monetary penalty up to $119,942 per violation (2024 adjusted)",
            "Termination from Medicare/Medicaid participation",
            "Civil suit by harmed individual",
            "On-call physician penalty for refusal or failure to appear",
            "Hospital and physician penalties are independent",
        ),
        "exceptions": (
            "Declared national emergency with pandemic exception waiver",
            "Patient leaves before MSE can be completed (document attempt)",
            "Hospital-owned urgent care that is not on campus and does not hold itself out as an ED",
        ),
        "applies_to": (
            "encounter",
            "patient",
            "staff",
        ),
    },
    "EMTALA_STABILIZATION": {
        "reg_id": "REG-EMTALA-002",
        "name": "EMTALA - Stabilization Requirement",
        "regulation_type": "federal",
        "category": "emtala",
        "description": (
            "If an emergency medical condition is identified during the MSE, the "
            "hospital must provide stabilizing treatment within its capability and "
            "capacity before discharge or transfer. The patient's condition must be "
            "stabilized such that no material deterioration is reasonably likely "
            "during or resulting from transfer."
        ),
        "requirements": (
            "Provide stabilizing treatment within hospital capability and capacity",
            "Continue treatment until emergency medical condition is resolved or stabilized",
            "For labor: deliver the child and placenta before transfer unless transfer benefits outweigh risks",
            "Stabilization must occur before discharge or transfer",
            "Physician must certify patient is stabilized before discharge",
            "If unstable, must meet transfer requirements before moving patient",
        ),
        "documentation_elements": (
            "Emergency medical condition identified",
            "Stabilizing treatment provided with times",
            "Reassessment of condition after treatment",
            "Physician certification of stabilization",
            "Vital signs demonstrating stability",
            "Condition at time of disposition decision",
        ),
        "violations_consequences": (
            "Civil monetary penalty up to $119,942 per violation",
            "Termination from Medicare/Medicaid",
            "Personal liability for physician who signed off on premature discharge",
            "Negligence per se in malpractice litigation",
        ),
        "exceptions": (
            "Patient refuses stabilizing treatment (document informed refusal)",
            "Appropriate transfer under EMTALA transfer provisions",
            "Patient leaves against medical advice (document AMA discussion)",
        ),
        "applies_to": (
            "encounter",
            "patient",
            "staff",
            "treatment_plan",
        ),
    },
    "EMTALA_TRANSFER": {
        "reg_id": "REG-EMTALA-003",
        "name": "EMTALA - Transfer Requirements",
        "regulation_type": "federal",
        "category": "emtala",
        "description": (
            "An appropriate transfer of an unstable patient requires physician "
            "certification that the medical benefits of transfer outweigh risks, "
            "acceptance by the receiving facility, transfer with qualified personnel "
            "and equipment, and all available medical records sent with the patient."
        ),
        "requirements": (
            "Physician certifies benefits of transfer outweigh risks",
            "Receiving facility has accepted the transfer and has available capacity",
            "Transferring hospital sends all available medical records",
            "Transfer conducted with qualified personnel and appropriate equipment",
            "Receiving hospital has agreed to provide stabilizing treatment",
            "Patient (or legal representative) gives informed consent when possible",
            "Receiving hospital must accept if it has specialized capability and capacity",
        ),
        "documentation_elements": (
            "Physician certification with risks and benefits",
            "Name and contact of accepting physician at receiving facility",
            "Informed consent for transfer (or reason consent not obtained)",
            "Mode of transport and personnel qualifications",
            "Copies of medical records sent with patient",
            "Time of transfer departure",
            "Patient condition at time of transfer",
            "Treatment provided during transport",
        ),
        "violations_consequences": (
            "Receiving hospital penalty for refusal when it has capability and capacity",
            "Transferring hospital penalty for inappropriate transfer",
            "Civil monetary penalty per violation",
            "Malpractice liability for adverse outcomes during inappropriate transfer",
        ),
        "exceptions": (
            "Patient requests transfer in writing after being informed of risks",
            "Physician certifies benefits outweigh risks for unstable patient",
            "Hospital lacks capability to stabilize — transfer is appropriate",
        ),
        "applies_to": (
            "encounter",
            "patient",
            "staff",
            "transfer",
        ),
    },
    "INFORMED_CONSENT": {
        "reg_id": "REG-CONSENT-001",
        "name": "Informed Consent",
        "regulation_type": "state",
        "category": "consent",
        "description": (
            "Before performing a procedure or treatment, the physician must obtain "
            "the patient's voluntary and informed consent. The patient must be "
            "informed of the diagnosis, proposed treatment, risks, benefits, "
            "alternatives, and the risk of no treatment."
        ),
        "requirements": (
            "Disclose the diagnosis or condition being treated",
            "Explain the proposed procedure or treatment in lay terms",
            "Describe material risks and potential complications",
            "Describe expected benefits of the procedure",
            "Discuss reasonable alternatives including no treatment",
            "Allow the patient to ask questions",
            "Verify the patient has decision-making capacity",
            "Obtain consent from a legally authorized representative if patient lacks capacity",
        ),
        "documentation_elements": (
            "Procedure or treatment described",
            "Risks discussed with patient",
            "Benefits discussed with patient",
            "Alternatives discussed including no treatment",
            "Patient questions and answers provided",
            "Patient or representative signature",
            "Witness signature",
            "Date and time of consent",
            "Name of physician obtaining consent",
        ),
        "violations_consequences": (
            "Battery or assault charge for procedure without consent",
            "Malpractice liability for inadequate informed consent",
            "Medical board disciplinary action",
            "Hospital sanctions for pattern of noncompliance",
        ),
        "exceptions": (
            "Life-threatening emergency where delay for consent would endanger patient",
            "Patient is unconscious with no available surrogate and delay is dangerous",
            "Therapeutic privilege (extremely narrow; disclosure would harm patient)",
            "Patient voluntarily waives right to information",
            "Legally mandated treatment (e.g., court-ordered evaluation)",
        ),
        "applies_to": (
            "patient",
            "procedure",
            "medication",
            "staff",
        ),
    },
    "AMA_DISCHARGE": {
        "reg_id": "REG-CONSENT-002",
        "name": "Against Medical Advice (AMA) Discharge",
        "regulation_type": "institutional",
        "category": "consent",
        "description": (
            "When a patient with decision-making capacity chooses to leave "
            "against medical advice, specific protocols must be followed to "
            "ensure the patient understands the risks, and thorough documentation "
            "must be completed to protect both the patient and the institution."
        ),
        "requirements": (
            "Assess and document patient decision-making capacity",
            "Explain specific risks of leaving including possible adverse outcomes",
            "Explain what further treatment is recommended and why",
            "Offer alternatives such as outpatient follow-up or partial treatment",
            "Inform patient they may return at any time",
            "Provide discharge medications and instructions when clinically appropriate",
            "Do not withhold belongings or personal property",
            "Contact social work or psychiatry if capacity is questionable",
        ),
        "documentation_elements": (
            "Capacity assessment findings",
            "Specific risks communicated to patient",
            "Recommended treatment plan the patient is declining",
            "Alternatives offered",
            "Patient's stated reasons for leaving",
            "Patient signature on AMA form (or refusal to sign documented)",
            "Witness signature",
            "Discharge medications and instructions provided",
            "Follow-up plan communicated",
        ),
        "violations_consequences": (
            "Malpractice liability if patient lacked capacity and was released",
            "EMTALA violation if MSE or stabilization was incomplete",
            "Regulatory scrutiny if pattern of inadequate AMA documentation",
            "Increased mortality risk for the patient",
        ),
        "exceptions": (
            "Patient who is an imminent danger to self or others (involuntary hold)",
            "Patient who lacks decision-making capacity (requires surrogate or legal process)",
            "Minor children (requires parental involvement or child protective services)",
        ),
        "applies_to": (
            "encounter",
            "patient",
            "staff",
            "disposition",
        ),
    },
    "PHYSICAL_RESTRAINT": {
        "reg_id": "REG-RESTRAINT-001",
        "name": "Physical Restraint Policy",
        "regulation_type": "accreditation",
        "category": "restraint",
        "description": (
            "Physical restraints may be used only as a last resort to protect "
            "the patient or others from imminent harm. CMS Conditions of "
            "Participation and The Joint Commission standards require time-limited "
            "orders, continuous monitoring, and regular reassessment."
        ),
        "requirements": (
            "Attempt least restrictive alternatives first (verbal de-escalation, 1:1 sitter)",
            "Physician or LIP must evaluate patient within 1 hour of restraint application",
            "Orders must specify type of restraint and clinical justification",
            "Violent/self-destructive behavior: order valid for 4 hours (adults)",
            "Non-violent/non-self-destructive: order valid for calendar day or per policy",
            "Continuous monitoring of circulation, sensation, skin integrity, and ROM",
            "Reassess need at least every 2 hours",
            "Offer nutrition, hydration, and toileting at regular intervals",
            "Release restraints as soon as the clinical indication resolves",
        ),
        "documentation_elements": (
            "Clinical justification for restraint",
            "Alternatives attempted and their outcomes",
            "Type of restraint applied (4-point, wrist, vest, etc.)",
            "Time of application",
            "Physician face-to-face evaluation within 1 hour",
            "Ongoing monitoring assessments (circulation, skin, ROM)",
            "Reassessment documentation every 2 hours",
            "Time of restraint removal and patient status",
            "Offers of nutrition, hydration, and toileting with times",
        ),
        "violations_consequences": (
            "CMS deficiency citation",
            "Joint Commission accreditation findings",
            "Battery charges if restraints used without clinical justification",
            "Wrongful death liability for restraint-related injury or asphyxiation",
            "State health department investigation",
        ),
        "exceptions": (
            "Forensic hold where law enforcement applies restraints under their authority",
            "Brief physical hold during emergency medication administration (document as chemical restraint)",
            "Post-operative immobilization devices not considered behavioral restraints",
        ),
        "applies_to": (
            "patient",
            "encounter",
            "staff",
            "clinical_task",
        ),
    },
    "CHEMICAL_RESTRAINT": {
        "reg_id": "REG-RESTRAINT-002",
        "name": "Chemical Restraint Policy",
        "regulation_type": "accreditation",
        "category": "restraint",
        "description": (
            "Chemical restraints (medications administered to restrict movement "
            "or behavior, not as standard treatment) carry the same regulatory "
            "requirements as physical restraints. They require clinical justification, "
            "physician order, monitoring, and documentation."
        ),
        "requirements": (
            "Attempt verbal de-escalation and environmental modification first",
            "Physician order required specifying medication, dose, route, and indication",
            "Monitor vital signs including oxygen saturation after administration",
            "Reassess patient response within 15 minutes of administration",
            "Document as restraint if medication is for behavior management not treatment",
            "Continuous observation for respiratory depression and hemodynamic changes",
            "Physician face-to-face evaluation within 1 hour",
        ),
        "documentation_elements": (
            "Clinical justification (agitation posing danger to self or others)",
            "De-escalation attempts and outcomes",
            "Medication, dose, route, and time of administration",
            "Vital signs before and after administration",
            "Patient response to medication",
            "Monitoring frequency and findings",
            "Adverse effects observed",
            "Physician evaluation within 1 hour documented",
        ),
        "violations_consequences": (
            "CMS deficiency citation for inadequate monitoring",
            "Wrongful death liability for unmonitored respiratory depression",
            "Medical board action for inappropriate chemical restraint",
            "Joint Commission accreditation findings",
        ),
        "exceptions": (
            "Medications given as part of standard psychiatric treatment (not restraint)",
            "Procedural sedation with appropriate sedation protocol (separate policy)",
            "Patient-requested anxiolytic medication at therapeutic doses",
        ),
        "applies_to": (
            "patient",
            "encounter",
            "staff",
            "medication",
            "clinical_task",
        ),
    },
    "MANDATORY_REPORTING": {
        "reg_id": "REG-REPORT-001",
        "name": "Mandatory Reporting",
        "regulation_type": "state",
        "category": "reporting",
        "description": (
            "Healthcare professionals are mandated reporters for specific conditions "
            "including suspected child abuse or neglect, elder abuse, domestic violence, "
            "gunshot wounds, stab wounds, and certain communicable diseases. Failure to "
            "report carries criminal penalties in most jurisdictions."
        ),
        "requirements": (
            "Report suspected child abuse or neglect to child protective services immediately",
            "Report suspected elder abuse or dependent adult abuse to adult protective services",
            "Report gunshot wounds to law enforcement regardless of circumstances",
            "Report stab wounds and assault injuries per state law",
            "Report suspected human trafficking",
            "Report certain communicable diseases to public health authorities",
            "Report suspected impaired drivers per state law",
            "Do not delay treatment to make reports",
            "Reporter has immunity from civil liability for good-faith reports",
        ),
        "documentation_elements": (
            "Basis for suspicion (physical findings, history inconsistencies, disclosures)",
            "Agency and individual reported to",
            "Date and time of report",
            "Name of reporter",
            "Report reference number if provided",
            "Actions taken to ensure patient safety",
            "Photographs of injuries (with consent or per policy for minors)",
        ),
        "violations_consequences": (
            "Criminal misdemeanor for failure to report (most states)",
            "Civil liability for damages resulting from failure to report",
            "Medical board disciplinary action",
            "Hospital sanctions and mandatory retraining",
            "Felony charge in some states for repeated failure to report child abuse",
        ),
        "exceptions": (
            "Attorney-client privilege (does not apply to healthcare providers)",
            "Clergy privilege varies by state and generally does not apply in ED",
            "Spousal privilege does not override mandatory reporting obligations",
        ),
        "applies_to": (
            "patient",
            "encounter",
            "staff",
            "clinical_note",
        ),
    },
    "CONTROLLED_SUBSTANCE": {
        "reg_id": "REG-CONTROLLED-001",
        "name": "Controlled Substance Documentation",
        "regulation_type": "federal",
        "category": "controlled_substance",
        "description": (
            "The Controlled Substances Act and DEA regulations require strict "
            "documentation and chain of custody for all Schedule II-V medications "
            "administered in the emergency department. State prescription drug "
            "monitoring programs (PDMPs) add additional requirements."
        ),
        "requirements": (
            "Verify patient identity before administering controlled substances",
            "Check state PDMP before prescribing opioids in non-emergency situations",
            "Document indication for each controlled substance administered",
            "Dual verification (two-nurse or nurse-pharmacist) for waste of partial doses",
            "Maintain controlled substance inventory log with running count",
            "Report discrepancies in controlled substance counts immediately",
            "Prescriber must have active DEA registration",
            "Discharge prescriptions for Schedule II limited per state law",
        ),
        "documentation_elements": (
            "Patient identification verification method",
            "PDMP check result and date (for prescriptions)",
            "Medication name, dose, route, and time administered",
            "Clinical indication for controlled substance",
            "Administering nurse and verifying witness for waste",
            "Amount wasted and witness signature",
            "Automated dispensing cabinet transaction log",
            "Prescriber DEA number on discharge prescriptions",
        ),
        "violations_consequences": (
            "DEA investigation and potential license revocation",
            "State medical board action",
            "Criminal charges for diversion or inadequate record-keeping",
            "Hospital loss of DEA registration affecting entire pharmacy",
            "CMS deficiency citation during survey",
        ),
        "exceptions": (
            "Emergency administration to unconscious patient (document rationale post-hoc)",
            "Three-day emergency supply provision under 21 CFR 290.10",
            "Hospice and end-of-life exceptions to PDMP check requirements in some states",
        ),
        "applies_to": (
            "patient",
            "encounter",
            "medication",
            "staff",
        ),
    },
    "CAPACITY_ASSESSMENT": {
        "reg_id": "REG-CONSENT-003",
        "name": "Patient Capacity Assessment",
        "regulation_type": "institutional",
        "category": "consent",
        "description": (
            "Decision-making capacity is assessed at the bedside by the treating "
            "physician. It is decision-specific and may fluctuate. A patient may "
            "have capacity for some decisions but not others. Capacity is distinct "
            "from legal competency, which is a judicial determination."
        ),
        "requirements": (
            "Assess capacity for each significant medical decision",
            "Evaluate four components: understanding, appreciation, reasoning, and expression of choice",
            "Understanding: patient can paraphrase the condition and proposed treatment",
            "Appreciation: patient acknowledges the condition applies to them",
            "Reasoning: patient can weigh risks and benefits and explain rationale",
            "Expression of choice: patient can clearly state a consistent decision",
            "Reassess capacity if clinical condition changes (intoxication clearing, delirium)",
            "Do not equate disagreement with physician recommendation with lack of capacity",
            "Obtain psychiatry consult for complex or contested capacity determinations",
        ),
        "documentation_elements": (
            "Specific decision being assessed",
            "Assessment of each component: understanding, appreciation, reasoning, choice",
            "Patient's own words demonstrating understanding or lack thereof",
            "Clinical factors affecting capacity (intoxication, delirium, pain, medications)",
            "Whether capacity is present, absent, or uncertain",
            "Plan if capacity is absent (surrogate decision-maker, psychiatry consult)",
            "Time of assessment",
            "Name of assessing physician",
        ),
        "violations_consequences": (
            "Battery liability for treating a capacitated patient who refuses",
            "Negligence liability for discharging an incapacitated patient",
            "EMTALA violation if incapacitated patient leaves without stabilization",
            "Malpractice claim if capacity assessment is inadequate or undocumented",
        ),
        "exceptions": (
            "Implied consent in life-threatening emergencies with unconscious patient",
            "Court-ordered treatment overriding patient refusal",
            "Previously executed advance directive that addresses the current situation",
            "Minor deemed emancipated by state law",
        ),
        "applies_to": (
            "patient",
            "encounter",
            "staff",
            "disposition",
        ),
    },
}


def load_regulations(
    regulation_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Regulatory]:
    """Load regulatory entities.

    When external regulation_data is provided, converts all entries.
    Otherwise falls back to the bundled subset.

    Args:
        regulation_data: Optional dict of reg_key -> regulation data.

    Returns:
        Dict of reg_key -> Regulatory.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, Regulatory] = {}

    source = regulation_data if regulation_data is not None else _BUNDLED_REGULATIONS

    for key, data in source.items():
        reg = Regulatory(
            id=f"REG-{key}",
            entity_type=EntityType.REGULATORY,
            created_at=now,
            updated_at=now,
            reg_id=data.get("reg_id", f"REG-{key}"),
            name=data.get("name", key),
            regulation_type=data.get("regulation_type", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            requirements=tuple(data.get("requirements", ())),
            documentation_elements=tuple(data.get("documentation_elements", ())),
            violations_consequences=tuple(data.get("violations_consequences", ())),
            exceptions=tuple(data.get("exceptions", ())),
            applies_to=tuple(data.get("applies_to", ())),
            active=data.get("active", True),
        )
        result[key] = reg

    return result
