"""
Mock insurance verification (pVerify / Availity stand-in).
Works for any outpatient medical or dental specialty.
"""
from typing import Optional

MOCK_PLANS = {
    "aetna": {
        "carrier": "Aetna PPO",
        "status": "active",
        "in_network": True,
        "annual_deductible": 1500,
        "deductible_met": 600,
        "out_of_pocket_max": 5000,
        "out_of_pocket_met": 600,
        "specialist_copay": 50,
        "primary_copay": 30,
        "preventive_coverage": 100,
        "prior_auth_required_for": ["MRI", "CT scan", "physical therapy >6 visits"],
    },
    "bcbs": {
        "carrier": "Blue Cross Blue Shield PPO",
        "status": "active",
        "in_network": True,
        "annual_deductible": 1000,
        "deductible_met": 250,
        "out_of_pocket_max": 4500,
        "out_of_pocket_met": 250,
        "specialist_copay": 45,
        "primary_copay": 25,
        "preventive_coverage": 100,
        "prior_auth_required_for": ["surgery", "inpatient", "specialty drugs"],
    },
    "cigna": {
        "carrier": "Cigna PPO",
        "status": "active",
        "in_network": True,
        "annual_deductible": 2000,
        "deductible_met": 0,
        "out_of_pocket_max": 6000,
        "out_of_pocket_met": 0,
        "specialist_copay": 60,
        "primary_copay": 35,
        "preventive_coverage": 100,
        "prior_auth_required_for": ["specialist visits", "imaging"],
    },
    "united": {
        "carrier": "United Healthcare Choice Plus",
        "status": "active",
        "in_network": True,
        "annual_deductible": 1200,
        "deductible_met": 800,
        "out_of_pocket_max": 4000,
        "out_of_pocket_met": 800,
        "specialist_copay": 50,
        "primary_copay": 30,
        "preventive_coverage": 100,
        "prior_auth_required_for": ["durable medical equipment", "surgery"],
    },
    "medicare": {
        "carrier": "Medicare Part B",
        "status": "active",
        "in_network": True,
        "annual_deductible": 240,
        "deductible_met": 0,
        "out_of_pocket_max": None,
        "out_of_pocket_met": 0,
        "specialist_copay": "20% after deductible",
        "primary_copay": "20% after deductible",
        "preventive_coverage": 100,
        "prior_auth_required_for": ["home health", "durable medical equipment"],
    },
    "delta dental": {
        "carrier": "Delta Dental PPO",
        "status": "active",
        "in_network": True,
        "annual_max": 2000,
        "annual_max_remaining": 1450,
        "deductible": 50,
        "deductible_met": 50,
        "preventive_coverage": 100,
        "basic_coverage": 80,
        "major_coverage": 50,
        "prior_auth_required_for": ["crowns", "implants", "orthodontics"],
    },
}


def verify_insurance(
    insurance_company: str,
    member_id: str,
    group_number: Optional[str] = None,
    patient_dob: Optional[str] = None,
    policy_holder_name: Optional[str] = None,
    procedure_type: Optional[str] = None,
) -> dict:
    carrier_key = next(
        (k for k in MOCK_PLANS if k in insurance_company.lower()),
        None,
    )

    if not carrier_key:
        return {
            "status": "out_of_network",
            "verified": False,
            "message": (
                f"We are not currently in-network with {insurance_company}. "
                "We can still see you as an out-of-network patient — costs may be higher. "
                "Would you like information on our self-pay rates?"
            ),
        }

    plan = dict(MOCK_PLANS[carrier_key])
    plan["member_id"] = member_id
    plan["group_number"] = group_number
    plan["verified"] = True

    if procedure_type:
        prior_auth = plan.get("prior_auth_required_for", [])
        needs_auth = any(procedure_type.lower() in p.lower() for p in prior_auth)
        plan["procedure_estimate"] = {
            "procedure": procedure_type,
            "prior_auth_required": needs_auth,
            "note": (
                "Prior authorization may be needed — we'll handle that for you."
                if needs_auth
                else "No prior authorization expected for this visit type."
            ),
        }

    return plan
