import json
from collections import Counter, defaultdict
from datetime import datetime

from django.conf import settings
from django.shortcuts import render

DATA_SOURCE_DIR = settings.BASE_DIR / 'data_source'
MONTHS_FR = [
    'janv.',
    'fevr.',
    'mars',
    'avr.',
    'mai',
    'juin',
    'juil.',
    'aout',
    'sept.',
    'oct.',
    'nov.',
    'dec.',
]
MOJIBAKE_MARKERS = ('\u00c3', '\u00c2', '\u00e2')
HOST_LABELS = {
    '2014': 'Bresil',
    '2018': 'Russie',
}
STADIUM_COORDINATES = {
    '2014': {
        'maracana': (-22.9121, -43.2302),
        'nacionaldebrasilia': (-15.7835, -47.8992),
        'corinthians': (-23.5453, -46.4742),
        'castelao': (-3.8070, -38.5220),
        'mineirao': (-19.8659, -43.9710),
        'fontenova': (-12.9789, -38.5048),
        'pantanal': (-15.6031, -56.1210),
        'amazonia': (-3.0831, -60.0280),
        'dasdunas': (-5.8269, -35.2132),
        'beirario': (-30.0654, -51.2368),
        'pernambuco': (-8.0199, -34.9783),
        'dabaixada': (-25.4481, -49.2767),
    },
    '2018': {
        'samara': (53.2780, 50.2377),
        'nizhnynovgorod': (56.3373, 43.9639),
        'volgograd': (48.7340, 44.5480),
        'ekaterinburg': (56.8325, 60.5736),
        'mordovia': (54.1818, 45.2039),
        'rostov': (47.2098, 39.7384),
        'kaliningrad': (54.6980, 20.5337),
        'kazan': (55.8200, 49.1603),
        'fisht': (43.4022, 39.9550),
        'saintpetersburg': (59.9728, 30.2219),
        'spartak': (55.8181, 37.4403),
        'luzhniki': (55.7158, 37.5538),
    },
}


def dashboard(request):
    editions = discover_editions()
    if not editions:
        return render(
            request,
            'worldcup/dashboard.html',
            {
                'editions': [],
                'selected_edition': {
                    'slug': '',
                    'name': 'Aucune edition disponible',
                    'kind_label': 'Donnees manquantes',
                    'description': 'Ajoutez des fichiers JSON dans data_source pour alimenter le dashboard.',
                },
                'hero_stats': [],
                'featured_match': empty_featured_match(),
                'board_matches': [],
                'board_title': 'Aucun match',
                'board_intro': 'Les donnees du tournoi seront affichees ici.',
                'groups': [],
                'venues': [],
                'venue_map': empty_venue_map(),
                'stage_cards': [],
            },
        )

    selected_slug = request.GET.get('edition') or default_edition_slug(editions)
    selected_edition = next(
        (edition for edition in editions if edition['slug'] == selected_slug),
        editions[0],
    )

    for edition in editions:
        edition['is_selected'] = edition['slug'] == selected_edition['slug']

    tournament = load_json(selected_edition['file'])
    groups_data = load_json(selected_edition['folder'] / 'worldcup.groups.json')
    standings_data = load_json(selected_edition['folder'] / 'worldcup.standings.json')
    stadiums_data = load_json(selected_edition['folder'] / 'worldcup.stadiums.json')
    teams_data = load_json(selected_edition['folder'] / 'worldcup.teams.json')

    matches = normalize_matches(tournament)
    groups = build_groups(groups_data, standings_data, matches)
    venues = build_venues(selected_edition['slug'], stadiums_data, matches)
    venue_map = build_venue_map(selected_edition, venues)
    stage_cards = build_stage_cards(matches)
    featured_match = build_featured_match(matches)
    hero_stats = build_hero_stats(matches, groups, venues)
    board_matches, board_title, board_intro = build_match_board(matches)

    selected_edition['description'] = build_edition_description(
        selected_edition,
        matches,
        teams_data,
        groups,
    )

    context = {
        'editions': editions,
        'selected_edition': selected_edition,
        'hero_stats': hero_stats,
        'featured_match': featured_match,
        'board_matches': board_matches,
        'board_title': board_title,
        'board_intro': board_intro,
        'groups': groups,
        'venues': venues,
        'venue_map': venue_map,
        'stage_cards': stage_cards,
    }
    return render(request, 'worldcup/dashboard.html', context)


def discover_editions():
    editions = []
    if not DATA_SOURCE_DIR.exists():
        return editions

    for folder in DATA_SOURCE_DIR.iterdir():
        if not folder.is_dir():
            continue

        worldcup_file = folder / 'worldcup.json'
        club_file = folder / 'clubworldcup.json'

        if worldcup_file.exists():
            file_path = worldcup_file
            kind_label = 'Coupe du monde'
        elif club_file.exists():
            file_path = club_file
            kind_label = 'Mondial des clubs'
        else:
            continue

        payload = load_json(file_path)
        editions.append(
            {
                'slug': folder.name,
                'year': int(folder.name) if folder.name.isdigit() else 0,
                'name': payload.get('name', folder.name),
                'short_name': payload.get('name', folder.name).replace('World Cup ', '').replace('Club World Cup ', ''),
                'kind_label': kind_label,
                'file': file_path,
                'folder': folder,
            }
        )

    return sorted(editions, key=lambda edition: edition['year'], reverse=True)


def default_edition_slug(editions):
    national_edition = next(
        (edition for edition in editions if edition['kind_label'] == 'Coupe du monde'),
        None,
    )
    return (national_edition or editions[0])['slug']


def load_json(path):
    if not path.exists():
        return {}

    with path.open(encoding='utf-8') as file:
        return repair_text(json.load(file))


def repair_text(value):
    if isinstance(value, dict):
        return {key: repair_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_text(item) for item in value]
    if isinstance(value, str):
        if any(marker in value for marker in MOJIBAKE_MARKERS):
            try:
                return value.encode('latin-1').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                return value
        return value
    return value


def normalize_matches(tournament):
    matches = []

    if tournament.get('rounds'):
        for round_block in tournament.get('rounds', []):
            round_name = round_block.get('name', '')
            for match in round_block.get('matches', []):
                matches.append(build_match_card(match, round_name))
    else:
        for match in tournament.get('matches', []):
            matches.append(build_match_card(match, match.get('round', '')))

    return sorted(matches, key=match_sort_key)


def build_match_card(match, fallback_round):
    round_name = match.get('round') or fallback_round or 'Affiche'
    date_label = format_date_fr(match.get('date'))
    team1_name = team_name(match.get('team1'))
    team2_name = team_name(match.get('team2'))
    team1_code = team_code(match.get('team1'))
    team2_code = team_code(match.get('team2'))
    score1, score2, score_note = extract_score(match)
    group_name = match.get('group') or (round_name if round_name.startswith('Group ') else '')
    stadium = match.get('stadium') or {}
    city = match.get('city', '')
    stadium_name = stadium.get('name', '')
    location_label = ' - '.join(part for part in [stadium_name, city] if part)
    has_score = score1 is not None and score2 is not None

    return {
        'round': round_name,
        'round_label': group_name or round_name,
        'group': group_name,
        'date_label': date_label,
        'date': match.get('date', ''),
        'time': match.get('time', ''),
        'sort_key': parse_datetime(match.get('date'), match.get('time')),
        'team1_name': team1_name,
        'team1_code': team1_code,
        'team2_name': team2_name,
        'team2_code': team2_code,
        'score1': score1,
        'score2': score2,
        'score_note': score_note,
        'has_score': has_score,
        'status_label': 'Termine' if has_score else 'A venir',
        'stadium_name': stadium_name,
        'city': city,
        'location_label': location_label,
        'is_placeholder': team1_name == 'N.N.' or team2_name == 'N.N.',
    }


def extract_score(match):
    if 'score1' in match or 'score2' in match:
        score1 = match.get('score1')
        score2 = match.get('score2')

        if score1 is not None and score2 is not None:
            if match.get('score1et') is not None and match.get('score2et') is not None:
                return match['score1et'], match['score2et'], 'ap.'
            if match.get('score1p') is not None and match.get('score2p') is not None:
                return match['score1p'], match['score2p'], 'tab'
            return score1, score2, ''

    score = match.get('score') or {}
    if score.get('et'):
        return score['et'][0], score['et'][1], 'ap.'
    if score.get('ft'):
        return score['ft'][0], score['ft'][1], ''

    return None, None, ''


def build_groups(groups_data, standings_data, matches):
    groups_index = {}
    team_codes = {}

    for match in matches:
        if match['team1_code']:
            team_codes[match['team1_name']] = match['team1_code']
        if match['team2_code']:
            team_codes[match['team2_name']] = match['team2_code']

    for group in groups_data.get('groups', []):
        groups_index[group['name']] = {
            'name': group['name'],
            'teams': [build_team_chip(team, team_codes) for team in group.get('teams', [])],
            'standings': [],
        }

    for group in standings_data.get('groups', []):
        group_name = group['name']
        groups_index.setdefault(
            group_name,
            {
                'name': group_name,
                'teams': [],
                'standings': [],
            },
        )
        rows = []
        for row in group.get('standings', []):
            team = row.get('team', {})
            team_name_value = team_name(team)
            rows.append(
                {
                    'pos': row.get('pos', 0),
                    'team_name': team_name_value,
                    'team_code': team_code(team) or team_codes.get(team_name_value, ''),
                    'played': row.get('played', 0),
                    'won': row.get('won', 0),
                    'drawn': row.get('drawn', 0),
                    'lost': row.get('lost', 0),
                    'goal_diff': row.get('goals_for', 0) - row.get('goals_against', 0),
                    'pts': row.get('pts', 0),
                    'is_qualified': row.get('pos', 0) <= 2,
                }
            )
        groups_index[group_name]['standings'] = rows
        if not groups_index[group_name]['teams']:
            groups_index[group_name]['teams'] = [build_team_chip(row['team_name'], team_codes) for row in rows]

    derived_groups = defaultdict(list)
    for match in matches:
        if not match['group']:
            continue
        derived_groups[match['group']].append(match['team1_name'])
        derived_groups[match['group']].append(match['team2_name'])

    for group_name, names in derived_groups.items():
        groups_index.setdefault(
            group_name,
            {
                'name': group_name,
                'teams': [],
                'standings': [],
            },
        )
        if not groups_index[group_name]['teams']:
            seen = set()
            chips = []
            for name in names:
                if name in seen or name == 'N.N.':
                    continue
                seen.add(name)
                chips.append(build_team_chip(name, team_codes))
            groups_index[group_name]['teams'] = chips

    return [groups_index[name] for name in sorted(groups_index)]


def build_team_chip(team_value, team_codes):
    name = team_name(team_value)
    return {
        'name': name,
        'code': team_code(team_value) or team_codes.get(name, ''),
    }


def build_venues(edition_slug, stadiums_data, matches):
    venues = []
    match_counts = Counter(
        match['stadium_name']
        for match in matches
        if match['stadium_name']
    )

    for stadium in stadiums_data.get('stadiums', []):
        coordinates = lookup_stadium_coordinates(edition_slug, stadium.get('key', ''))
        venues.append(
            {
                'key': stadium.get('key', ''),
                'name': stadium.get('name', 'Stade a confirmer'),
                'city': stadium.get('city', ''),
                'meta': stadium.get('timezone', ''),
                'capacity': stadium.get('capacity', 0),
                'matches_count': match_counts.get(stadium.get('name', ''), 0),
                'lat': coordinates[0] if coordinates else None,
                'lng': coordinates[1] if coordinates else None,
            }
        )

    if venues:
        venues.sort(key=lambda venue: venue['capacity'], reverse=True)
        return venues

    derived_venues = []
    seen = set()
    for match in matches:
        if not match['location_label'] or match['location_label'] in seen:
            continue
        seen.add(match['location_label'])
        derived_venues.append(
            {
                'key': '',
                'name': match['stadium_name'] or match['city'],
                'city': match['city'],
                'meta': match['round_label'],
                'capacity': 0,
                'matches_count': 1,
                'lat': None,
                'lng': None,
            }
        )
    return derived_venues


def build_venue_map(selected_edition, venues):
    markers = []

    positioned_venues = [venue for venue in venues if venue['lat'] is not None and venue['lng'] is not None]
    bounds = coordinate_bounds(positioned_venues)

    for venue in venues:
        if venue['lat'] is None or venue['lng'] is None:
            continue

        markers.append(
            {
                'name': venue['name'],
                'city': venue['city'],
                'meta': venue['meta'],
                'capacity': venue['capacity'],
                'matches_count': venue['matches_count'],
                'lat': venue['lat'],
                'lng': venue['lng'],
                'x_percent': project_longitude(venue['lng'], bounds),
                'y_percent': project_latitude(venue['lat'], bounds),
            }
        )

    return {
        'map_id': 'stadium-map',
        'host_label': HOST_LABELS.get(selected_edition['slug'], selected_edition['name']),
        'markers': markers,
        'marker_count': len(markers),
        'single_zoom': 10,
    }


def build_stage_cards(matches):
    stage_counter = Counter()
    stage_order = []

    for match in matches:
        stage = match['round']
        if stage not in stage_counter:
            stage_order.append(stage)
        stage_counter[stage] += 1

    return [{'name': stage, 'count': stage_counter[stage]} for stage in stage_order[:8]]


def build_featured_match(matches):
    if not matches:
        return empty_featured_match()

    final_match = next(
        (
            match
            for match in reversed(matches)
            if match['round'].lower() == 'final'
            and match['has_score']
            and not match['is_placeholder']
        ),
        None,
    )
    if final_match:
        winner = (
            final_match['team1_name']
            if final_match['score1'] > final_match['score2']
            else final_match['team2_name']
        )
        return {
            **final_match,
            'badge': 'Finale',
            'headline': winner,
            'summary': 'Champion du tournoi.',
        }

    opening_match = next(
        (
            match
            for match in matches
            if not match['is_placeholder']
            and 'qualification' not in match['round'].lower()
        ),
        None,
    )
    if opening_match:
        return {
            **opening_match,
            'badge': 'Ouverture',
            'headline': opening_match['round_label'],
            'summary': 'Match d ouverture du tournoi.',
        }

    fallback = matches[0]
    return {
        **fallback,
        'badge': 'Vue generale',
        'headline': fallback['round_label'],
        'summary': 'Vue generale du tournoi.',
    }


def build_hero_stats(matches, groups, venues):
    team_names = {
        name
        for match in matches
        for name in [match['team1_name'], match['team2_name']]
        if name and name != 'N.N.'
    }
    total_goals = sum(
        match['score1'] + match['score2']
        for match in matches
        if match['has_score']
    )
    stage_count = len({match['round'] for match in matches if match['round']})

    return [
        {'label': 'Matchs', 'value': len(matches)},
        {'label': 'Equipes', 'value': len(team_names)},
        {'label': 'Groupes' if groups else 'Phases', 'value': len(groups) or stage_count},
        {
            'label': 'Buts' if total_goals else 'Stades' if venues else 'Tours',
            'value': total_goals or len(venues) or stage_count,
        },
    ]


def build_match_board(matches):
    played_matches = [match for match in matches if match['has_score']]
    display_pool = [
        match
        for match in matches
        if not match['is_placeholder'] and 'qualification' not in match['round'].lower()
    ] or [match for match in matches if not match['is_placeholder']]

    if len(played_matches) >= 6:
        board_matches = sorted(played_matches, key=match_sort_key, reverse=True)[:6]
        board_title = 'Derniers resultats'
        board_intro = 'Les matchs les plus recents du tournoi.'
    else:
        board_matches = display_pool[:6]
        board_title = 'Match Center'
        board_intro = 'Les principales affiches de la competition.'

    return board_matches, board_title, board_intro


def build_edition_description(selected_edition, matches, teams_data, groups):
    continents = Counter(
        team.get('continent')
        for team in teams_data.get('teams', [])
        if team.get('continent')
    )
    if continents:
        top_continent, top_count = continents.most_common(1)[0]
        stage_total = len(groups) or len({match['round'] for match in matches})
        return (
            f"{selected_edition['kind_label']} avec {len(matches)} matchs, "
            f"{stage_total} phases de competition et {top_count} equipes issues de "
            f"{top_continent.lower()}."
        )

    return (
        f"{selected_edition['kind_label']} avec {len(matches)} matchs "
        f"et {len(groups) or len({match['round'] for match in matches})} phases de competition."
    )


def empty_featured_match():
    return {
        'badge': 'A venir',
        'headline': 'Match Center',
        'summary': 'Les informations du tournoi apparaitront ici.',
        'round_label': 'Tableau principal',
        'team1_name': 'Equipe A',
        'team2_name': 'Equipe B',
        'team1_code': '',
        'team2_code': '',
        'score1': None,
        'score2': None,
        'score_note': '',
        'has_score': False,
        'date_label': 'Date a confirmer',
        'time': '',
        'location_label': '',
    }


def empty_venue_map():
    return {
        'map_id': 'stadium-map',
        'host_label': '',
        'markers': [],
        'marker_count': 0,
        'single_zoom': 10,
    }


def team_name(team):
    if isinstance(team, dict):
        return team.get('name', 'N.N.')
    return team or 'N.N.'


def team_code(team):
    if isinstance(team, dict):
        return team.get('code', '')
    if isinstance(team, str) and '(' in team and team.endswith(')'):
        code = team.rsplit('(', 1)[1].rstrip(')')
        if 2 <= len(code) <= 4:
            return code
    return ''


def parse_datetime(date_value, time_value):
    if not date_value:
        return None
    time_part = time_value or '00:00'
    try:
        return datetime.strptime(f'{date_value} {time_part}', '%Y-%m-%d %H:%M')
    except ValueError:
        return None


def match_sort_key(match):
    return match['sort_key'] or datetime.max


def format_date_fr(date_value):
    if not date_value:
        return 'Date a confirmer'
    try:
        parsed_date = datetime.strptime(date_value, '%Y-%m-%d')
    except ValueError:
        return date_value
    return f"{parsed_date.day} {MONTHS_FR[parsed_date.month - 1]} {parsed_date.year}"


def lookup_stadium_coordinates(edition_slug, stadium_key):
    return STADIUM_COORDINATES.get(edition_slug, {}).get(stadium_key)


def coordinate_bounds(venues):
    if not venues:
        return {
            'min_lat': -90,
            'max_lat': 90,
            'min_lng': -180,
            'max_lng': 180,
        }

    latitudes = [venue['lat'] for venue in venues]
    longitudes = [venue['lng'] for venue in venues]

    min_lat = min(latitudes)
    max_lat = max(latitudes)
    min_lng = min(longitudes)
    max_lng = max(longitudes)

    lat_padding = max((max_lat - min_lat) * 0.12, 1.2)
    lng_padding = max((max_lng - min_lng) * 0.12, 1.2)

    return {
        'min_lat': min_lat - lat_padding,
        'max_lat': max_lat + lat_padding,
        'min_lng': min_lng - lng_padding,
        'max_lng': max_lng + lng_padding,
    }


def project_longitude(longitude, bounds):
    min_lng = bounds['min_lng']
    max_lng = bounds['max_lng']
    if max_lng == min_lng:
        return 50.0
    return round(8 + ((longitude - min_lng) / (max_lng - min_lng)) * 84, 2)


def project_latitude(latitude, bounds):
    min_lat = bounds['min_lat']
    max_lat = bounds['max_lat']
    if max_lat == min_lat:
        return 50.0
    return round(10 + (1 - ((latitude - min_lat) / (max_lat - min_lat))) * 80, 2)
