"""Team name mappings for all supported sports (F-026).

Each sport has a dict mapping canonical short name → list of aliases.
Aliases must include the full name as used by The Odds API,
plus any short forms Polymarket uses in question text.
"""

from __future__ import annotations

# =============================================================================
# NBA (30 teams) — moved from odds_api.py
# =============================================================================

NBA_TEAM_NAMES: dict[str, list[str]] = {
    "lakers": ["los angeles lakers", "lakers", "la lakers"],
    "celtics": ["boston celtics", "celtics", "boston"],
    "warriors": ["golden state warriors", "warriors", "golden state"],
    "bucks": ["milwaukee bucks", "bucks", "milwaukee"],
    "heat": ["miami heat", "heat", "miami"],
    "suns": ["phoenix suns", "suns", "phoenix"],
    "nuggets": ["denver nuggets", "nuggets", "denver"],
    "76ers": ["philadelphia 76ers", "76ers", "sixers", "philadelphia"],
    "nets": ["brooklyn nets", "nets", "brooklyn"],
    "bulls": ["chicago bulls", "bulls", "chicago"],
    "knicks": ["new york knicks", "knicks", "new york"],
    "clippers": ["los angeles clippers", "clippers", "la clippers"],
    "mavericks": ["dallas mavericks", "mavericks", "dallas"],
    "hawks": ["atlanta hawks", "hawks", "atlanta"],
    "grizzlies": ["memphis grizzlies", "grizzlies", "memphis"],
    "timberwolves": ["minnesota timberwolves", "timberwolves", "minnesota"],
    "thunder": ["oklahoma city thunder", "thunder", "okc", "oklahoma city"],
    "cavaliers": ["cleveland cavaliers", "cavaliers", "cleveland", "cavs"],
    "pelicans": ["new orleans pelicans", "pelicans", "new orleans"],
    "rockets": ["houston rockets", "rockets", "houston"],
    "kings": ["sacramento kings", "kings", "sacramento"],
    "raptors": ["toronto raptors", "raptors", "toronto"],
    "pacers": ["indiana pacers", "pacers", "indiana"],
    "magic": ["orlando magic", "magic", "orlando"],
    "pistons": ["detroit pistons", "pistons", "detroit"],
    "hornets": ["charlotte hornets", "hornets", "charlotte"],
    "wizards": ["washington wizards", "wizards", "washington"],
    "spurs": ["san antonio spurs", "spurs", "san antonio"],
    "jazz": ["utah jazz", "jazz", "utah"],
    "blazers": ["portland trail blazers", "trail blazers", "blazers", "portland"],
}

# =============================================================================
# NHL (32 teams)
# =============================================================================

NHL_TEAM_NAMES: dict[str, list[str]] = {
    # Atlantic
    "bruins": ["boston bruins", "bruins", "boston"],
    "sabres": ["buffalo sabres", "sabres", "buffalo"],
    "red_wings": ["detroit red wings", "red wings", "detroit"],
    "panthers": ["florida panthers", "panthers", "florida"],
    "canadiens": ["montreal canadiens", "canadiens", "montreal", "habs"],
    "senators": ["ottawa senators", "senators", "ottawa"],
    "lightning": ["tampa bay lightning", "lightning", "tampa bay", "tampa"],
    "maple_leafs": ["toronto maple leafs", "maple leafs", "toronto", "leafs"],
    # Metropolitan
    "hurricanes": ["carolina hurricanes", "hurricanes", "carolina"],
    "blue_jackets": ["columbus blue jackets", "blue jackets", "columbus"],
    "devils": ["new jersey devils", "devils", "new jersey"],
    "islanders": ["new york islanders", "islanders", "ny islanders"],
    "rangers": ["new york rangers", "rangers", "ny rangers"],
    "flyers": ["philadelphia flyers", "flyers", "philadelphia"],
    "penguins": ["pittsburgh penguins", "penguins", "pittsburgh"],
    "capitals": ["washington capitals", "capitals", "washington"],
    # Central
    "utah_hc": ["utah hockey club", "utah hc", "utah", "utah mammoth"],
    "blackhawks": ["chicago blackhawks", "blackhawks", "chicago"],
    "avalanche": ["colorado avalanche", "avalanche", "colorado"],
    "stars": ["dallas stars", "stars", "dallas"],
    "wild": ["minnesota wild", "wild", "minnesota"],
    "predators": ["nashville predators", "predators", "nashville"],
    "blues": ["st. louis blues", "blues", "st louis blues", "st louis"],
    "jets": ["winnipeg jets", "jets", "winnipeg"],
    # Pacific
    "ducks": ["anaheim ducks", "ducks", "anaheim"],
    "flames": ["calgary flames", "flames", "calgary"],
    "oilers": ["edmonton oilers", "oilers", "edmonton"],
    "kings_la": ["los angeles kings", "kings", "la kings"],
    "sharks": ["san jose sharks", "sharks", "san jose"],
    "kraken": ["seattle kraken", "kraken", "seattle"],
    "canucks": ["vancouver canucks", "canucks", "vancouver"],
    "golden_knights": ["vegas golden knights", "golden knights", "vegas", "vgk"],
}

# =============================================================================
# Bundesliga (18 teams — 2025-26 season)
# =============================================================================

BUNDESLIGA_TEAM_NAMES: dict[str, list[str]] = {
    "bayern": ["bayern munich", "bayern", "fc bayern", "fc bayern munich"],
    "dortmund": ["borussia dortmund", "dortmund", "bvb"],
    "leverkusen": ["bayer leverkusen", "leverkusen", "bayer 04"],
    "leipzig": ["rb leipzig", "leipzig", "rasenballsport leipzig"],
    "frankfurt": ["eintracht frankfurt", "frankfurt", "sge"],
    "freiburg": ["sc freiburg", "freiburg"],
    "stuttgart": ["vfb stuttgart", "stuttgart"],
    "gladbach": ["borussia monchengladbach", "gladbach", "monchengladbach", "bmg"],
    "union_berlin": ["union berlin", "fc union berlin", "1. fc union berlin"],
    "wolfsburg": ["vfl wolfsburg", "wolfsburg"],
    "bremen": ["werder bremen", "bremen", "sv werder bremen"],
    "hoffenheim": ["tsg hoffenheim", "hoffenheim", "1899 hoffenheim"],
    "augsburg": ["fc augsburg", "augsburg"],
    "mainz": ["1. fsv mainz 05", "mainz", "mainz 05"],
    "heidenheim": ["1. fc heidenheim", "heidenheim", "fc heidenheim"],
    "bochum": ["vfl bochum", "bochum"],
    "st_pauli": ["fc st. pauli", "st. pauli", "st pauli"],
    "holstein_kiel": ["holstein kiel", "kiel"],
}

# =============================================================================
# EPL (20 teams — 2025-26 season)
# =============================================================================

EPL_TEAM_NAMES: dict[str, list[str]] = {
    "arsenal": ["arsenal", "arsenal fc"],
    "aston_villa": ["aston villa", "villa"],
    "bournemouth": ["afc bournemouth", "bournemouth"],
    "brentford": ["brentford", "brentford fc"],
    "brighton": ["brighton and hove albion", "brighton", "brighton & hove albion"],
    "chelsea": ["chelsea", "chelsea fc"],
    "crystal_palace": ["crystal palace", "palace"],
    "everton": ["everton", "everton fc"],
    "fulham": ["fulham", "fulham fc"],
    "ipswich": ["ipswich town", "ipswich"],
    "leicester": ["leicester city", "leicester"],
    "liverpool": ["liverpool", "liverpool fc"],
    "man_city": ["manchester city", "man city", "man. city", "mcfc"],
    "man_utd": ["manchester united", "man united", "man utd", "man. united", "mufc"],
    "newcastle": ["newcastle united", "newcastle", "newcastle utd"],
    "nott_forest": ["nottingham forest", "nott'm forest", "forest"],
    "southampton": ["southampton", "saints"],
    "tottenham": ["tottenham hotspur", "tottenham", "spurs"],
    "west_ham": ["west ham united", "west ham", "west ham utd"],
    "wolves": ["wolverhampton wanderers", "wolves", "wolverhampton"],
}

# =============================================================================
# Serie A (20 teams — 2025-26 season)
# =============================================================================

SERIE_A_TEAM_NAMES: dict[str, list[str]] = {
    "inter": ["inter milan", "inter", "fc internazionale", "internazionale"],
    "ac_milan": ["ac milan", "milan"],
    "juventus": ["juventus", "juve", "juventus fc"],
    "napoli": ["napoli", "ssc napoli"],
    "atalanta": ["atalanta", "atalanta bc"],
    "roma": ["as roma", "roma"],
    "lazio": ["lazio", "ss lazio"],
    "fiorentina": ["fiorentina", "acf fiorentina"],
    "bologna": ["bologna", "bologna fc"],
    "torino": ["torino", "torino fc"],
    "monza": ["monza", "ac monza"],
    "genoa": ["genoa", "genoa cfc"],
    "udinese": ["udinese", "udinese calcio"],
    "empoli": ["empoli", "empoli fc"],
    "cagliari": ["cagliari", "cagliari calcio"],
    "lecce": ["lecce", "us lecce"],
    "verona": ["hellas verona", "verona"],
    "sassuolo": ["sassuolo", "us sassuolo"],
    "como": ["como 1907", "como"],
    "venezia": ["venezia", "venezia fc"],
}

# =============================================================================
# Ligue 1 (18 teams — 2025-26 season)
# =============================================================================

LIGUE_1_TEAM_NAMES: dict[str, list[str]] = {
    "psg": ["paris saint-germain", "psg", "paris saint germain", "paris sg"],
    "marseille": ["olympique de marseille", "marseille", "om"],
    "monaco": ["as monaco", "monaco"],
    "lille": ["lille osc", "lille", "losc"],
    "lyon": ["olympique lyonnais", "lyon", "ol"],
    "nice": ["ogc nice", "nice"],
    "lens": ["rc lens", "lens"],
    "rennes": ["stade rennais", "rennes"],
    "strasbourg": ["rc strasbourg", "strasbourg"],
    "toulouse": ["toulouse fc", "toulouse"],
    "reims": ["stade de reims", "reims"],
    "montpellier": ["montpellier hsc", "montpellier"],
    "nantes": ["fc nantes", "nantes"],
    "brest": ["stade brestois", "brest"],
    "le_havre": ["le havre ac", "le havre"],
    "clermont": ["clermont foot", "clermont"],
    "auxerre": ["aj auxerre", "auxerre"],
    "angers": ["angers sco", "angers"],
}

# =============================================================================
# La Liga (20 teams — 2025-26 season)
# =============================================================================

LA_LIGA_TEAM_NAMES: dict[str, list[str]] = {
    "real_madrid": ["real madrid", "r. madrid", "real"],
    "barcelona": ["fc barcelona", "barcelona", "barca"],
    "atletico": ["atletico madrid", "atletico", "atl. madrid", "atletico de madrid"],
    "real_sociedad": ["real sociedad", "sociedad", "la real"],
    "athletic_bilbao": ["athletic bilbao", "athletic club", "bilbao"],
    "real_betis": ["real betis", "betis"],
    "villarreal": ["villarreal", "villarreal cf"],
    "sevilla": ["sevilla fc", "sevilla"],
    "valencia": ["valencia cf", "valencia"],
    "osasuna": ["ca osasuna", "osasuna"],
    "celta_vigo": ["celta vigo", "celta", "rc celta"],
    "getafe": ["getafe cf", "getafe"],
    "girona": ["girona fc", "girona"],
    "rayo_vallecano": ["rayo vallecano", "rayo"],
    "alaves": ["deportivo alaves", "alaves"],
    "mallorca": ["rcd mallorca", "mallorca"],
    "las_palmas": ["ud las palmas", "las palmas"],
    "cadiz": ["cadiz cf", "cadiz"],
    "leganes": ["cd leganes", "leganes"],
    "espanyol": ["rcd espanyol", "espanyol"],
}

# =============================================================================
# UCL — Champions League (top European clubs, merged from leagues)
# =============================================================================

UCL_TEAM_NAMES: dict[str, list[str]] = {
    # Spain
    "real_madrid": ["real madrid", "r. madrid", "real"],
    "barcelona": ["fc barcelona", "barcelona", "barca"],
    "atletico": ["atletico madrid", "atletico", "atl. madrid"],
    # England
    "liverpool": ["liverpool", "liverpool fc"],
    "man_city": ["manchester city", "man city", "mcfc"],
    "arsenal": ["arsenal", "arsenal fc"],
    "chelsea": ["chelsea", "chelsea fc"],
    "tottenham": ["tottenham hotspur", "tottenham", "spurs"],
    "man_utd": ["manchester united", "man united", "man utd", "mufc"],
    "aston_villa": ["aston villa", "villa"],
    # Germany
    "bayern": ["bayern munich", "bayern", "fc bayern"],
    "dortmund": ["borussia dortmund", "dortmund", "bvb"],
    "leverkusen": ["bayer leverkusen", "leverkusen"],
    "leipzig": ["rb leipzig", "leipzig"],
    # Italy
    "inter": ["inter milan", "inter", "fc internazionale"],
    "ac_milan": ["ac milan", "milan"],
    "juventus": ["juventus", "juve"],
    "napoli": ["napoli", "ssc napoli"],
    "atalanta": ["atalanta", "atalanta bc"],
    "bologna": ["bologna", "bologna fc"],
    # France
    "psg": ["paris saint-germain", "psg", "paris saint germain"],
    "marseille": ["olympique de marseille", "marseille", "om"],
    "monaco": ["as monaco", "monaco"],
    "lille": ["lille osc", "lille"],
    "brest": ["stade brestois", "brest"],
    # Netherlands / Portugal / others
    "psv": ["psv eindhoven", "psv"],
    "feyenoord": ["feyenoord", "feyenoord rotterdam"],
    "benfica": ["sl benfica", "benfica"],
    "porto": ["fc porto", "porto"],
    "sporting": ["sporting cp", "sporting", "sporting lisbon"],
    "celtic": ["celtic fc", "celtic", "celtic glasgow"],
    "brugge": ["club brugge", "brugge"],
    "salzburg": ["red bull salzburg", "salzburg", "rb salzburg"],
    "dinamo_zagreb": ["dinamo zagreb", "zagreb"],
    "shakhtar": ["shakhtar donetsk", "shakhtar"],
    "galatasaray": ["galatasaray", "galatasaray sk"],
}
