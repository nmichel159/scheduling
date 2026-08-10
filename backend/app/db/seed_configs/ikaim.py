"""Deterministic I.KAIM demo staff, qualifications, and August absences."""

from datetime import date
import hashlib
import random


AMBULANCE_NAME = "I.KAIM"
MANAGER_EMAIL = "noro.michel159@gmail.com"

LOZKO = "Lôžko"
ANESTEZIA = "Anestézia"
REPLANTACIE = "Replantácie"
AFTERNOON = "15:00–19:00"

COMPETENCES = [
    {"name": LOZKO, "required_count": 2},
    {"name": ANESTEZIA, "required_count": 2},
    {"name": REPLANTACIE, "required_count": 1},
    {"name": AFTERNOON, "required_count": 1},
]

# Grey rows marked as inactive in the source screenshot are intentionally omitted.
STAFF = [
    ("vladimir.hudak@ikaim.test", "MUDr. Vladimír Hudák, PhD.", [LOZKO, ANESTEZIA]),
    ("tomas.pallas@ikaim.test", "MUDr. Tomáš Pallas", [LOZKO, ANESTEZIA]),
    ("sindy.grande@ikaim.test", "MUDr. Sindy Grande", [LOZKO, ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("zaneta.hutnanova@ikaim.test", "MUDr. Žaneta Hutňanová", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("henrieta.janikova-sallaiova@ikaim.test", "MUDr. Henrieta Janíková - Sallaiová", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("blanka.kubisova@ikaim.test", "MUDr. Blanka Kubišová", [LOZKO, ANESTEZIA]),
    ("lucia.kerul-kmecova@ikaim.test", "MUDr. Lucia Keruľ-Kmecová", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("blanka.komanova@ikaim.test", "MUDr. Blanka Komanová", [LOZKO, ANESTEZIA]),
    ("jan.korcek@ikaim.test", "MUDr. Ján Korček", [LOZKO, ANESTEZIA]),
    ("martina.kotorova@ikaim.test", "MUDr. Martina Kotorová", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("roman.kysel@ikaim.test", "MUDr. Roman Kyseľ", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("maria.lences@ikaim.test", "MUDr. Mária Lenčeš", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("terezia.mikulova@ikaim.test", "MUDr. Terézia Mikulová", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("roman.schmidt@ikaim.test", "MUDr. Roman Schmidt", [LOZKO, ANESTEZIA]),
    ("julius.skvasik@ikaim.test", "MUDr. Július Skvašik", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("jana.sucha@ikaim.test", "MUDr. Jana Suchá", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("jana.spakova@ikaim.test", "Jana Špáková", [ANESTEZIA, REPLANTACIE]),
    ("jana.simonova@ikaim.test", "doc. MUDr. Jana Šimonová, PhD., MPH.", [LOZKO, ANESTEZIA]),
    ("lucia.simova@ikaim.test", "MUDr. Lucia Šimová", [ANESTEZIA, REPLANTACIE]),
    ("michal.zahorak@ikaim.test", "MUDr. Michal Záhorák, MPH.", [LOZKO, ANESTEZIA, REPLANTACIE]),
    ("judita.capkova@ikaim.test", "MUDr. Judita Čapková, PhD.", [ANESTEZIA]),
    ("vladimir.filka@ikaim.test", "MUDr. Vladimír Filka", [ANESTEZIA, REPLANTACIE]),
    ("lucia.futasova@ikaim.test", "MUDr. Lucia Futašová", [ANESTEZIA, REPLANTACIE]),
    ("peter.lences@ikaim.test", "MUDr. Peter Lenčeš", [ANESTEZIA, REPLANTACIE]),
    ("ladislav.neubert@ikaim.test", "MUDr. Ladislav Neubert, MPH.", [ANESTEZIA, REPLANTACIE]),
    ("marek.varga@ikaim.test", "MUDr. Marek Varga", [ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("tomas.kampe@ikaim.test", "Tomáš Kampe", [ANESTEZIA, AFTERNOON]),
    ("nikola.katorova@ikaim.test", "MUDr. Nikola Katorová", [LOZKO, ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("kristian.semancik@ikaim.test", "MUDr. Kristián Semančík", [LOZKO, ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("ester.tomajkova@ikaim.test", "MUDr. Ester Tomajková", [LOZKO, ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("veronika.urbancikova@ikaim.test", "MUDr. Veronika Urbančíková", [LOZKO, ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("matus.zembiak@ikaim.test", "MUDr. Matúš Zembiak", [LOZKO, ANESTEZIA, AFTERNOON, REPLANTACIE]),
    ("ema.varga-koscova@ikaim.test", "MUDr. Ema Varga-Košťová", [ANESTEZIA, AFTERNOON, REPLANTACIE]),
]


def _unavailable_dates(email: str, position: int) -> list[date]:
    """Return four or five stable pseudo-random August 2026 dates."""
    seed = int.from_bytes(
        hashlib.sha256(f"I.KAIM|2026-08|{email}".encode("utf-8")).digest()[:8],
        "big",
    )
    day_count = 4 + position % 2
    return [date(2026, 8, day) for day in sorted(random.Random(seed).sample(range(1, 32), day_count))]


USERS = [{"email": email, "full_name": full_name} for email, full_name, _ in STAFF]
AMBULANCE = {
    "name": AMBULANCE_NAME,
    "description": "I. klinika anestéziológie a intenzívnej medicíny",
    "manager_email": MANAGER_EMAIL,
    "isurgent": False,
}
AMBULANCE_ASSIGNMENTS = {email: [AMBULANCE_NAME] for email, _, _ in STAFF}
ROLE_ASSIGNMENTS = {email: ["EMPLOYEE"] for email, _, _ in STAFF}
USER_COMPETENCE_ASSIGNMENTS = {
    email: {AMBULANCE_NAME: competence_names}
    for email, _, competence_names in STAFF
}
UNAVAILABILITIES = [
    {
        "user_email": email,
        "date_absent": unavailable_date,
        "reason": "MOCK_IKAIM_UNAVAILABLE",
    }
    for position, (email, _, _) in enumerate(STAFF)
    for unavailable_date in _unavailable_dates(email, position)
]
GENERATED_SCHEDULES = [
    {"ambulance_name": AMBULANCE_NAME, "month": 8, "year": 2026}
]
