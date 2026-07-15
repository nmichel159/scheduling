PRIMARY_USERS = [
    {"email": "a14325999@gmail.com", "full_name": "Leader A"},
    {"email": "alexthesecond0000@gmail.com", "full_name": "Alex the Second"},
    {"email": "noro.michel159@gmail.com", "full_name": "Noro Michel 159"},
    {"email": "noro.michel@gmail.com", "full_name": "Noro Michel"},
]

ADDITIONAL_USERS = [
    {"email": "martin.hudak@example.com", "full_name": "Martin Hudak"},
    {"email": "jana.kovacova@example.com", "full_name": "Jana Kovacova"},
    {"email": "peter.novak@example.com", "full_name": "Peter Novak"},
    {"email": "lucia.horvathova@example.com", "full_name": "Lucia Horvathova"},
    {"email": "tomas.balog@example.com", "full_name": "Tomas Balog"},
    {"email": "eva.mistrikova@example.com", "full_name": "Eva Mistrikova"},
    {"email": "michal.simon@example.com", "full_name": "Michal Simon"},
    {"email": "katarina.danko@example.com", "full_name": "Katarina Danko"},
    {"email": "andrej.svec@example.com", "full_name": "Andrej Svec"},
    {"email": "veronika.krizova@example.com", "full_name": "Veronika Krizova"},
    {"email": "filip.benko@example.com", "full_name": "Filip Benko"},
    {"email": "nina.molnarova@example.com", "full_name": "Nina Molnarova"},
    {"email": "roman.varga@example.com", "full_name": "Roman Varga"},
    {"email": "simona.liptakova@example.com", "full_name": "Simona Liptakova"},
    {"email": "adam.urban@example.com", "full_name": "Adam Urban"},
]

USERS = PRIMARY_USERS + ADDITIONAL_USERS

AMBULANCES = [
    {
        "name": "ambulancia1",
        "description": "Prva ambulancia",
        "manager_email": "noro.michel159@gmail.com",
        "isurgent": False,
    },
    {
        "name": "ambulancia2",
        "description": "Druha ambulancia",
        "manager_email": "a14325999@gmail.com",
        "isurgent": False,
    },
    {
        "name": "ambulancia3",
        "description": "Tretia ambulancia pod rovnakou spravou ako ambulancia1",
        "manager_email": "noro.michel159@gmail.com",
        "isurgent": False,
    },
    {
        "name": "ambulancia4",
        "description": "Stvrta ambulancia",
        "manager_email": "a14325999@gmail.com",
        "isurgent": False,
    },
    {
        "name": "urgentna_ambulancia1",
        "description": "Urgentna ambulancia pre Leader A",
        "manager_email": "a14325999@gmail.com",
        "isurgent": True,
    },
    {
        "name": "urgentna_ambulancia2",
        "description": "Urgentna ambulancia pre Alex the Second",
        "manager_email": "alexthesecond0000@gmail.com",
        "isurgent": True,
    },
    {
        "name": "urgentna_ambulancia3",
        "description": "Urgentna ambulancia pre Noro Michel 159",
        "manager_email": "noro.michel159@gmail.com",
        "isurgent": True,
    },
    {
        "name": "urgentna_ambulancia4",
        "description": "Urgentna ambulancia pre Noro Michel",
        "manager_email": "noro.michel@gmail.com",
        "isurgent": True,
    },
]

COMPETENCES = {
    "ambulancia1": ["role1", "role2", "role3"],
    "ambulancia2": ["rola1", "rola2"],
    "ambulancia3": ["triage", "odbery"],
    "ambulancia4": ["recepcia", "kontrola"],
}

AMBULANCE_ASSIGNMENTS = {
    "alexthesecond0000@gmail.com": ["ambulancia1"],
    "noro.michel159@gmail.com": ["ambulancia1", "ambulancia3"],
    "a14325999@gmail.com": ["ambulancia2"],
}
