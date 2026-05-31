"""Clinical-fidelity tests for the em_vocab drug classes and the whole-token
matcher (2026-05-31 grader audit + EM-physician adjudication).

Two defect classes are locked here:
  1. Member-name qualifiers ("labetalol", "levetiracetam", "platelet
     transfusion", "fosphenytoin") were NOT class keys, so the matcher fell
     back to a single literal-substring match and every other class member
     slipped a safety_critical gate. New classes close that bypass.
  2. Raw substring matching let short surface forms ("ms" for morphine, a "ct"
     qualifier) match INSIDE unrelated words ("symptoms", "instructions"),
     false-failing correct restraint trajectories. Whole-token matching fixes it.

Each class also carries explicit false-fail guards: the CORRECT alternative
drugs must NEVER trip the gate.
"""

from __future__ import annotations

from healthcraft.tasks.em_vocab import is_known_class
from healthcraft.tasks.evaluator import _audit_entry_matches_params, _token_present


def _matches(entry: dict, klass: str) -> bool:
    """Does an audit entry match a class-named qualifier?"""
    return _audit_entry_matches_params(entry, {"_match": klass})


class TestWholeTokenMatching:
    def test_ms_does_not_match_inside_symptoms(self) -> None:
        # The morphine synonym "ms" must not match inside "symptoms".
        assert _token_present("ms", "reviewed the patient's symptoms and vitals") is False
        assert _token_present("ms", "no hamstring tenderness") is False

    def test_ms_matches_as_a_token(self) -> None:
        assert _token_present("ms", "gave ms 4 mg iv") is True

    def test_ct_does_not_match_inside_instructions(self) -> None:
        assert _token_present("ct", "provided discharge instructions and activity advice") is False

    def test_ct_matches_as_a_token(self) -> None:
        assert _token_present("ct", "ordered ct head without contrast") is True

    def test_multiword_form_still_matches(self) -> None:
        assert _token_present("packed red blood cells", "transfuse packed red blood cells") is True


class TestNewClassesAreRegistered:
    def test_classes_known(self) -> None:
        for klass in ("hydantoin", "antiepileptic", "iv_antihypertensive", "platelet", "triptan"):
            assert is_known_class(klass), f"{klass} should be a known em_vocab class"


class TestHydantoinClass:
    def test_phenytoin_and_fosphenytoin_caught(self) -> None:
        assert _matches({"medication": "phenytoin"}, "hydantoin") is True
        assert _matches({"medication": "fosphenytoin"}, "hydantoin") is True
        assert _matches({"medication": "dilantin"}, "hydantoin") is True

    def test_correct_alternatives_not_caught(self) -> None:
        # MW-016: levetiracetam / valproate are the correct alternatives.
        assert _matches({"medication": "levetiracetam"}, "hydantoin") is False
        assert _matches({"medication": "valproate"}, "hydantoin") is False
        assert _matches({"medication": "lorazepam"}, "hydantoin") is False


class TestAntiepilepticClass:
    def test_maintenance_aeds_caught(self) -> None:
        for drug in ("levetiracetam", "phenytoin", "valproate", "phenobarbital", "lacosamide"):
            assert _matches({"medication": drug}, "antiepileptic") is True, drug

    def test_benzodiazepines_excluded(self) -> None:
        # Abortive benzos (sedative class) are correct care, must NOT trip.
        for benzo in ("lorazepam", "midazolam", "diazepam", "ativan", "versed"):
            assert _matches({"medication": benzo}, "antiepileptic") is False, benzo

    def test_antipyretics_excluded(self) -> None:
        assert _matches({"medication": "acetaminophen"}, "antiepileptic") is False


class TestIvAntihypertensiveClass:
    def test_parenteral_agents_caught(self) -> None:
        for drug in (
            "labetalol",
            "nicardipine",
            "hydralazine",
            "nitroprusside",
            "esmolol",
            "clevidipine",
            "enalaprilat",
            "fenoldopam",
        ):
            assert _matches({"medication": drug}, "iv_antihypertensive") is True, drug

    def test_oral_home_ace_inhibitor_excluded(self) -> None:
        # NEG-004-C07 positively rewards resuming oral lisinopril — must NOT trip.
        assert _matches({"medication": "lisinopril"}, "iv_antihypertensive") is False
        assert _matches({"medication": "enalapril"}, "iv_antihypertensive") is False


class TestPlateletClass:
    def test_platelet_products_caught(self) -> None:
        for form in ("platelets", "platelet transfusion", "apheresis platelets", "plt"):
            assert _matches({"medication": form}, "platelet") is True, form

    def test_prbc_and_plasma_not_caught(self) -> None:
        # CR-041-C07 REQUIRES PRBC for Hgb 6.8; plasmapheresis is the TTP therapy.
        assert _matches({"product": "PRBC"}, "platelet") is False
        assert _matches({"product": "packed red blood cells"}, "platelet") is False
        assert _matches({"medication": "fresh frozen plasma"}, "platelet") is False
        assert _matches({"procedure": "plasmapheresis"}, "platelet") is False


class TestTriptanAndErgotClasses:
    def test_all_triptans_caught(self) -> None:
        for drug in (
            "sumatriptan",
            "rizatriptan",
            "eletriptan",
            "zolmitriptan",
            "naratriptan",
            "almotriptan",
            "frovatriptan",
            "maxalt",
            "relpax",
        ):
            assert _matches({"medication": drug}, "triptan") is True, drug

    def test_ergot_abortives_caught(self) -> None:
        assert _matches({"medication": "dihydroergotamine"}, "ergot_abortive") is True
        assert _matches({"medication": "dhe"}, "ergot_abortive") is True

    def test_correct_acag_therapy_not_caught(self) -> None:
        # The correct IOP-lowering agents must NEVER trip the migraine gate.
        for drug in ("acetazolamide", "timolol", "pilocarpine", "brimonidine", "mannitol"):
            assert _matches({"medication": drug}, "triptan") is False, drug


class TestExistingClassesUnregressed:
    def test_anticoagulant_still_matches(self) -> None:
        assert _matches({"medication": "enoxaparin"}, "anticoagulant") is True
        assert _matches({"medication": "heparin drip"}, "anticoagulant") is True

    def test_thrombolytic_still_matches(self) -> None:
        assert _matches({"medication": "alteplase"}, "thrombolytic") is True
        assert _matches({"medication": "tpa"}, "thrombolytic") is True
