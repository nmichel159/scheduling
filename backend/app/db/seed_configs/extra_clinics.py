"""Three more departments of the hospital, arranged around I.KAIM.

They are named after departments the hospital really runs, so that a demo
reads as a hospital rather than as a test fixture, but only the names are
real: the people on their rosters are invented, shuffled, and qualified at
random. Two of them -- the second anaesthesiology clinic and the paediatric
one -- have rosters of their own, which is what gives the hospital-wide
statistics something to compare.

The third, the emergency department, is deliberately not staffed from a pool of
its own: its roster is drawn from I.KAIM and from II.KAIM, so the demo
exercises the rule that a duty in one department blocks the same and the
neighbouring day in every other one.

That borrowed roster is also why every member of the urgent workplace is
qualified for both of its roles. Its people are already committed elsewhere by
the time it is scheduled, so the few days each of them has left have to be
usable for whichever role is still open on them; splitting the roster by role
would leave single-candidate days that no solver can rescue.
"""

from app.db.seed_configs.accounts import (
    SECOND_KAIM_MANAGER_EMAIL,
    IKAIM_EMPLOYEE_EMAIL,
    OVERSEER_EMAIL,
    KDAIM_MANAGER_EMAIL,
    URGENT_MANAGER_EMAIL,
)
from app.db.seed_configs.availability import monthly_calendar, stable_random
from app.db.seed_configs.qualifications import draw_qualifications, ensure_holders
from app.db.seed_configs.ikaim import (
    AMBULANCE_NAME as IKAIM_NAME,
    MEMBER_EMAILS as IKAIM_MEMBER_EMAILS,
    MONTHS,
    YEAR,
    is_approved,
)


SECOND_KAIM_NAME = "II.KAIM"
KDAIM_NAME = "KDAIM"
URGENT_NAME = "KUM"

UNAVAILABLE_REASON = "MOCK_DEMO_UNAVAILABLE"

#: Invented people the two rostered departments draw their staff from.
STAFF_POOL = [
    ("Adam Bartos", "adam.bartos"),
    ("Alena Zatkova", "alena.zatkova"),
    ("Barbora Hrncirova", "barbora.hrncirova"),
    ("Boris Michalik", "boris.michalik"),
    ("Daniela Kostkova", "daniela.kostkova"),
    ("David Lukacs", "david.lukacs"),
    ("Denisa Palkova", "denisa.palkova"),
    ("Dominik Ferko", "dominik.ferko"),
    ("Erika Sedlakova", "erika.sedlakova"),
    ("Filip Duris", "filip.duris"),
    ("Gabriela Ondrusova", "gabriela.ondrusova"),
    ("Igor Bencik", "igor.bencik"),
    ("Ivana Repkova", "ivana.repkova"),
    ("Jakub Hrivnak", "jakub.hrivnak"),
    ("Jarmila Cierna", "jarmila.cierna"),
    ("Juraj Belan", "juraj.belan"),
    ("Karol Zvara", "karol.zvara"),
    ("Klaudia Rusnakova", "klaudia.rusnakova"),
    ("Kristina Behunova", "kristina.behunova"),
    ("Ladislav Tkac", "ladislav.tkac"),
    ("Lenka Vavrova", "lenka.vavrova"),
    ("Lukas Chovanec", "lukas.chovanec"),
    ("Magdalena Kubanova", "magdalena.kubanova"),
    ("Marek Stefanik", "marek.stefanik"),
    ("Martina Gregova", "martina.gregova"),
    ("Matej Zilinsky", "matej.zilinsky"),
    ("Michaela Bielikova", "michaela.bielikova"),
    ("Miroslav Hanuliak", "miroslav.hanuliak"),
    ("Monika Strakova", "monika.strakova"),
    ("Natalia Jurkova", "natalia.jurkova"),
    ("Oliver Petrik", "oliver.petrik"),
    ("Patricia Vavrekova", "patricia.vavrekova"),
    ("Pavol Hrabovsky", "pavol.hrabovsky"),
    ("Radoslav Mikus", "radoslav.mikus"),
    ("Renata Klimova", "renata.klimova"),
    ("Samuel Odler", "samuel.odler"),
    ("Silvia Bartosova", "silvia.bartosova"),
    ("Stanislav Gajdos", "stanislav.gajdos"),
    ("Tatiana Hudecova", "tatiana.hudecova"),
    ("Vladimir Sabo", "vladimir.sabo"),
]

SECOND_KAIM_COMPETENCES = [
    {"name": "Lôžko", "required_count": 2},
    {"name": "Anestézia", "required_count": 1},
    {"name": "Konzíliá", "required_count": 1},
]
KDAIM_COMPETENCES = [
    {"name": "Detská anestézia", "required_count": 2},
    {"name": "Detská JIS", "required_count": 1},
]
URGENT_INTAKE = "Urgentný príjem"
URGENT_OBSERVATION = "Expektačné lôžka"
URGENT_COMPETENCES = [
    {"name": URGENT_INTAKE, "required_count": 1},
    {"name": URGENT_OBSERVATION, "required_count": 1},
]

#: How many of the pool each rostered department employs.
SECOND_KAIM_HEADCOUNT = 22
KDAIM_HEADCOUNT = 18
#: How many people the emergency department borrows from each of its sources.
URGENT_FROM_IKAIM = 20
URGENT_FROM_SECOND_KAIM = 14

_shuffled_pool = list(STAFF_POOL)
stable_random("demo-clinics", "roster").shuffle(_shuffled_pool)


def _emails(entries: list[tuple[str, str]]) -> list[str]:
    """Return the mock mailbox of every person in `entries`."""
    return [f"{slug}@demo.test" for _, slug in entries]


_SECOND_KAIM_POOL = _shuffled_pool[:SECOND_KAIM_HEADCOUNT]
_KDAIM_POOL = _shuffled_pool[SECOND_KAIM_HEADCOUNT : SECOND_KAIM_HEADCOUNT + KDAIM_HEADCOUNT]

SECOND_KAIM_STAFF_EMAILS = _emails(_SECOND_KAIM_POOL)
KDAIM_STAFF_EMAILS = _emails(_KDAIM_POOL)
# The overseer works this clinic too, which together with I.KAIM and the urgent
# workplace puts that account on three rosters.
SECOND_KAIM_MEMBER_EMAILS = SECOND_KAIM_STAFF_EMAILS + [OVERSEER_EMAIL]
# The urgent workplace's own scheduler also works a rota somewhere else, so the
# demo has somebody who builds one schedule and appears in another.
KDAIM_MEMBER_EMAILS = KDAIM_STAFF_EMAILS + [URGENT_MANAGER_EMAIL]

USERS = [
    {"email": f"{slug}@demo.test", "full_name": full_name}
    for full_name, slug in _SECOND_KAIM_POOL + _KDAIM_POOL
]


def _roster(
    workplace: str,
    competences: list[dict],
    emails: list[str],
) -> dict[str, list[str]]:
    """Draw random roles for a workplace and top up the under-covered ones."""
    names = [competence["name"] for competence in competences]
    return ensure_holders(
        workplace,
        draw_qualifications(workplace, names, emails),
        names,
        {
            competence["name"]: competence["required_count"] * 6
            for competence in competences
        },
    )


_SECOND_KAIM_QUALIFICATIONS = _roster(SECOND_KAIM_NAME, SECOND_KAIM_COMPETENCES, SECOND_KAIM_MEMBER_EMAILS)
_KDAIM_QUALIFICATIONS = _roster(
    KDAIM_NAME, KDAIM_COMPETENCES, KDAIM_MEMBER_EMAILS
)

# The overseer joins by name rather than by draw, and the account that is meant
# to be an employee of I.KAIM and of nothing else is kept out of the draw.
_urgent_candidates = [
    email
    for email in IKAIM_MEMBER_EMAILS
    if email not in {OVERSEER_EMAIL, IKAIM_EMPLOYEE_EMAIL}
]
_urgent_from_ikaim = sorted(
    stable_random("demo-clinics", "urgent", IKAIM_NAME).sample(
        _urgent_candidates, URGENT_FROM_IKAIM
    )
)
_urgent_from_second_kaim = sorted(
    stable_random("demo-clinics", "urgent", SECOND_KAIM_NAME).sample(
        SECOND_KAIM_STAFF_EMAILS, URGENT_FROM_SECOND_KAIM
    )
)
URGENT_MEMBER_EMAILS = _urgent_from_ikaim + _urgent_from_second_kaim + [OVERSEER_EMAIL]

AMBULANCES = [
    {
        "name": SECOND_KAIM_NAME,
        "description": "II. klinika anestéziológie a intenzívnej medicíny",
        "manager_email": SECOND_KAIM_MANAGER_EMAIL,
        "isurgent": False,
    },
    {
        "name": KDAIM_NAME,
        "description": "Klinika detskej anestéziológie a intenzívnej medicíny",
        "manager_email": KDAIM_MANAGER_EMAIL,
        "isurgent": False,
    },
    {
        "name": URGENT_NAME,
        "description": "Klinika urgentnej medicíny, obsadzovaná z I.KAIM a II.KAIM",
        "manager_email": URGENT_MANAGER_EMAIL,
        "isurgent": True,
    },
]

COMPETENCES = {
    SECOND_KAIM_NAME: SECOND_KAIM_COMPETENCES,
    KDAIM_NAME: KDAIM_COMPETENCES,
    URGENT_NAME: URGENT_COMPETENCES,
}

ROLE_ASSIGNMENTS = {
    email: ["EMPLOYEE"] for email in SECOND_KAIM_STAFF_EMAILS + KDAIM_STAFF_EMAILS
}

AMBULANCE_ASSIGNMENTS: dict[str, list[str]] = {}
for _email in SECOND_KAIM_MEMBER_EMAILS:
    AMBULANCE_ASSIGNMENTS.setdefault(_email, []).append(SECOND_KAIM_NAME)
for _email in KDAIM_MEMBER_EMAILS:
    AMBULANCE_ASSIGNMENTS.setdefault(_email, []).append(KDAIM_NAME)
for _email in URGENT_MEMBER_EMAILS:
    AMBULANCE_ASSIGNMENTS.setdefault(_email, []).append(URGENT_NAME)

USER_COMPETENCE_ASSIGNMENTS: dict[str, dict[str, list[str]]] = {}
for _email, _names in _SECOND_KAIM_QUALIFICATIONS.items():
    USER_COMPETENCE_ASSIGNMENTS.setdefault(_email, {})[SECOND_KAIM_NAME] = _names
for _email, _names in _KDAIM_QUALIFICATIONS.items():
    USER_COMPETENCE_ASSIGNMENTS.setdefault(_email, {})[KDAIM_NAME] = _names
for _email in URGENT_MEMBER_EMAILS:
    USER_COMPETENCE_ASSIGNMENTS.setdefault(_email, {})[URGENT_NAME] = [
        URGENT_INTAKE,
        URGENT_OBSERVATION,
    ]

UNAVAILABILITIES = monthly_calendar(
    SECOND_KAIM_STAFF_EMAILS + KDAIM_STAFF_EMAILS,
    YEAR,
    MONTHS,
    unavailable_reason=UNAVAILABLE_REASON,
)

# Ordered so that every workplace is solved against the duties already fixed
# elsewhere, and the urgent one -- whose people are the most constrained -- is
# solved last, when it can still see all of them.
GENERATED_SCHEDULES = [
    {
        "ambulance_name": ambulance_name,
        "month": month,
        "year": YEAR,
        "approved": is_approved(month),
    }
    for ambulance_name in (SECOND_KAIM_NAME, KDAIM_NAME, URGENT_NAME)
    for month in MONTHS
]
