"""I.KAIM: the demo profile's main workplace, staffed from the real roster.

This is the clinic every other mock workplace is arranged around. Its core
roster, qualifications and daily demand come from the department's own staffing
table; what the seed adds is a full year of self-reported absences and day
requests and an approved schedule for every month of that year, so the
calendar, the workload views and the yearly statistics all have something real
to show immediately after a database reset.

Two things here are deliberately invented on top of that table. The clinic runs
seven roles rather than the four the table lists, and how many of them are
staffed changes from month to month -- three in a quiet month, all seven in a
busy one -- because a workplace whose demand never moves makes the generator
look like a calendar filler rather than a planner. The department's own roster
is far too small to absorb the busy months at that demand, so it is reinforced
with invented colleagues, who carry most of the qualifications the three new
roles need.
"""

from app.db.seed_configs.accounts import (
    IKAIM_EMPLOYEE_EMAIL,
    IKAIM_SCHEDULER_EMAIL,
    OVERSEER_EMAIL,
)
from app.db.seed_configs.availability import monthly_calendar
from app.db.seed_configs.qualifications import draw_qualifications, ensure_holders


AMBULANCE_NAME = "I.KAIM"
MANAGER_EMAIL = IKAIM_SCHEDULER_EMAIL

LOZKO = "Lôžko"
ANESTEZIA = "Anestézia"
REPLANTACIE = "Replantácie"
AFTERNOON = "15:00–19:00"
KONZILIUM = "Konzíliá"
DETSKA = "Detská anestézia"
BOLEST = "Ambulancia bolesti"

#: Roles the department's own staffing table covers.
CORE_COMPETENCE_NAMES = [LOZKO, ANESTEZIA, REPLANTACIE, AFTERNOON]
#: Roles invented for the demo, drawn across the whole roster.
EXTRA_COMPETENCE_NAMES = [KONZILIUM, DETSKA, BOLEST]
COMPETENCE_NAMES = CORE_COMPETENCE_NAMES + EXTRA_COMPETENCE_NAMES

#: The demo year every mock workplace is scheduled for.
YEAR = 2026
#: Months scheduled up front, starting on the first of January.
MONTHS = tuple(range(1, 11))
#: Months whose schedule is already signed off. The months after it are drafts:
#: generated, visible, and still waiting for their manager, which is the state
#: a planner is actually in partway through a year.
APPROVED_THROUGH_MONTH = 9
UNAVAILABLE_REASON = "MOCK_IKAIM_UNAVAILABLE"


def is_approved(month: int) -> bool:
    """Whether the schedule generated for `month` is seeded as approved."""
    return month <= APPROVED_THROUGH_MONTH

#: The clinic's settled staffing: the four roles it has always run, at the
#: headcount its manager asked to keep. The last months of the year use it, so
#: it is also what stays in the database as the current configuration.
BASELINE_REQUIREMENTS = {LOZKO: 2, ANESTEZIA: 2, REPLANTACIE: 1, AFTERNOON: 1}

# How many people each role needs every day, month by month. A role a month
# leaves out is not staffed at all that month, so the number of roles in play
# swings between three and seven and the daily headcount between four and nine.
# The generator is given one of these profiles per month, and the last month's
# stays behind as the clinic's current configuration -- which is why the year
# ends on the baseline rather than on one of the experiments.
MONTHLY_REQUIREMENTS = {
    1: {LOZKO: 2, ANESTEZIA: 2, REPLANTACIE: 1},
    2: {LOZKO: 2, ANESTEZIA: 2, REPLANTACIE: 1, AFTERNOON: 1},
    3: {LOZKO: 2, ANESTEZIA: 2, REPLANTACIE: 1, AFTERNOON: 1, KONZILIUM: 1},
    4: {LOZKO: 2, ANESTEZIA: 1, AFTERNOON: 1},
    5: {
        LOZKO: 2,
        ANESTEZIA: 2,
        REPLANTACIE: 1,
        AFTERNOON: 1,
        KONZILIUM: 1,
        DETSKA: 1,
    },
    6: {LOZKO: 2, ANESTEZIA: 1, REPLANTACIE: 1, BOLEST: 1},
    7: {
        LOZKO: 2,
        ANESTEZIA: 2,
        REPLANTACIE: 1,
        AFTERNOON: 1,
        KONZILIUM: 1,
        DETSKA: 1,
        BOLEST: 1,
    },
    8: {LOZKO: 2, ANESTEZIA: 2, REPLANTACIE: 1, AFTERNOON: 1},
    9: dict(BASELINE_REQUIREMENTS),
    10: dict(BASELINE_REQUIREMENTS),
}

# The competence list starts from the profile of the last generated month,
# which the generator also leaves behind, so what a manager opens matches the
# newest schedule that was built from it.
COMPETENCES = [
    {"name": name, "required_count": MONTHLY_REQUIREMENTS[MONTHS[-1]].get(name, 0)}
    for name in COMPETENCE_NAMES
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

#: Invented colleagues who make the busy months coverable. They carry the two
#: ward roles outright and draw the rest, so the reinforcement lands where the
#: real roster is thinnest.
REINFORCEMENTS = [
    ("adela.bencurova@ikaim.test", "MUDr. Adela Benčurová"),
    ("andrea.polakova@ikaim.test", "MUDr. Andrea Poláková"),
    ("bohus.kramar@ikaim.test", "MUDr. Bohuš Kramár"),
    ("dusan.jancik@ikaim.test", "MUDr. Dušan Jančík"),
    ("emil.rovny@ikaim.test", "MUDr. Emil Rovný"),
    ("hana.olejnikova@ikaim.test", "MUDr. Hana Olejníková"),
    ("ivan.sokol@ikaim.test", "MUDr. Ivan Sokol"),
    ("iveta.bilska@ikaim.test", "MUDr. Iveta Bílská"),
    ("jozef.kmec@ikaim.test", "MUDr. Jozef Kmec"),
    ("katarina.rybarova@ikaim.test", "MUDr. Katarína Rybárová"),
    ("lubos.hric@ikaim.test", "MUDr. Ľuboš Hric"),
    ("marcela.jastrabova@ikaim.test", "MUDr. Marcela Jastrabová"),
    ("marian.zubaj@ikaim.test", "MUDr. Marián Zubaj"),
    ("nora.slavikova@ikaim.test", "MUDr. Nora Slavíková"),
    ("ondrej.bystricky@ikaim.test", "MUDr. Ondrej Bystrický"),
    ("pavlina.gerova@ikaim.test", "MUDr. Pavlína Gerová"),
    ("peter.hrusovsky@ikaim.test", "MUDr. Peter Hrušovský"),
    ("rastislav.demko@ikaim.test", "MUDr. Rastislav Demko"),
    ("sona.matejkova@ikaim.test", "MUDr. Soňa Matejková"),
    ("tibor.kolesar@ikaim.test", "MUDr. Tibor Kolesár"),
    ("viera.hlavacova@ikaim.test", "MUDr. Viera Hlaváčová"),
    ("zuzana.pavlikova@ikaim.test", "MUDr. Zuzana Pavlíková"),
]

#: Qualified holders each role needs across the roster. Several times the daily
#: demand, so a role still has candidates on the days its people are away.
MINIMUM_HOLDERS = {
    LOZKO: 30,
    ANESTEZIA: 30,
    REPLANTACIE: 22,
    AFTERNOON: 18,
    KONZILIUM: 18,
    DETSKA: 18,
    BOLEST: 18,
}

_reinforcement_qualifications = draw_qualifications(
    AMBULANCE_NAME,
    COMPETENCE_NAMES,
    [email for email, _ in REINFORCEMENTS],
    probability=0.5,
    always=(LOZKO, ANESTEZIA),
)

# Two real accounts work this rota so that signing in as either shows one's own
# duties and not only somebody else's: the overseer, who is on two other
# rosters as well, and an account that is an employee of this clinic and of
# nothing else. Their user rows come from the shared list of sign-in accounts,
# which is why neither is repeated in USERS below.
SIGN_IN_MEMBERS = [
    (OVERSEER_EMAIL, "Noro Micheľ", [LOZKO, ANESTEZIA, REPLANTACIE, KONZILIUM]),
    (IKAIM_EMPLOYEE_EMAIL, "Zamestnanec UNLP", [LOZKO, ANESTEZIA, DETSKA]),
]
MEMBERS = (
    STAFF
    + [
        (email, full_name, _reinforcement_qualifications[email])
        for email, full_name in REINFORCEMENTS
    ]
    + SIGN_IN_MEMBERS
)
MEMBER_EMAILS = [email for email, _, _ in MEMBERS]

# The reinforcements are drawn first and cover most of the shortfall, so the
# top-up below mostly hands out the three invented roles. It is free to add a
# real role to a real person as well when one is still short -- a role the
# roster cannot cover on some day would make that month infeasible, and a
# missing qualification is the cheaper inaccuracy of the two.
QUALIFICATIONS = ensure_holders(
    AMBULANCE_NAME,
    {email: names for email, _, names in MEMBERS},
    COMPETENCE_NAMES,
    MINIMUM_HOLDERS,
)

USERS = [
    {"email": email, "full_name": full_name} for email, full_name, _ in STAFF
] + [{"email": email, "full_name": full_name} for email, full_name in REINFORCEMENTS]
AMBULANCE = {
    "name": AMBULANCE_NAME,
    "description": "I. klinika anestéziológie a intenzívnej medicíny",
    "manager_email": MANAGER_EMAIL,
    "isurgent": False,
}
AMBULANCE_ASSIGNMENTS = {email: [AMBULANCE_NAME] for email in MEMBER_EMAILS}
#: Mock staff only: the roles of the real sign-in accounts are set centrally.
_SIGN_IN_EMAILS = {email for email, _, _ in SIGN_IN_MEMBERS}
ROLE_ASSIGNMENTS = {
    email: ["EMPLOYEE"] for email in MEMBER_EMAILS if email not in _SIGN_IN_EMAILS
}
USER_COMPETENCE_ASSIGNMENTS = {
    email: {AMBULANCE_NAME: names} for email, names in QUALIFICATIONS.items()
}
UNAVAILABILITIES = monthly_calendar(
    MEMBER_EMAILS,
    YEAR,
    MONTHS,
    unavailable_reason=UNAVAILABLE_REASON,
)
GENERATED_SCHEDULES = [
    {
        "ambulance_name": AMBULANCE_NAME,
        "month": month,
        "year": YEAR,
        "required_counts": MONTHLY_REQUIREMENTS[month],
        "approved": is_approved(month),
    }
    for month in MONTHS
]
