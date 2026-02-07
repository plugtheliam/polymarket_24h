"""TDD tests for NBA team name parser (Kent Beck style).

Red → Green → Refactor

Test cases based on actual Polymarket NBA market questions:
- "Mavericks vs. Spurs"
- "Warriors vs. Lakers"
- "76ers vs. Suns"
- "Knicks vs. Celtics"
"""

import pytest
from poly24h.strategy.nba_fair_value import NBATeamParser


class TestNBATeamParser:
    """Test suite for NBA team name extraction."""

    @pytest.fixture
    def parser(self):
        return NBATeamParser()

    # === Basic "Team1 vs. Team2" pattern ===
    
    def test_parse_mavericks_vs_spurs(self, parser):
        """Basic team vs team pattern."""
        team_a, team_b = parser.parse_teams("Mavericks vs. Spurs")
        assert team_a == "mavericks"
        assert team_b == "spurs"

    def test_parse_warriors_vs_lakers(self, parser):
        """Another basic pattern."""
        team_a, team_b = parser.parse_teams("Warriors vs. Lakers")
        assert team_a == "warriors"
        assert team_b == "lakers"

    def test_parse_knicks_vs_celtics(self, parser):
        """Eastern conference matchup."""
        team_a, team_b = parser.parse_teams("Knicks vs. Celtics")
        assert team_a == "knicks"
        assert team_b == "celtics"

    # === Special team names ===

    def test_parse_76ers_as_sixers(self, parser):
        """76ers should normalize to sixers."""
        team_a, team_b = parser.parse_teams("76ers vs. Suns")
        assert team_a == "sixers"
        assert team_b == "suns"

    def test_parse_trail_blazers(self, parser):
        """Trail Blazers is two words."""
        team_a, team_b = parser.parse_teams("Grizzlies vs. Trail Blazers")
        assert team_a == "grizzlies"
        assert team_b == "blazers"

    # === Case insensitivity ===

    def test_case_insensitive(self, parser):
        """Should handle any case."""
        team_a, team_b = parser.parse_teams("WARRIORS vs. LAKERS")
        assert team_a == "warriors"
        assert team_b == "lakers"

    def test_mixed_case(self, parser):
        """Mixed case should work."""
        team_a, team_b = parser.parse_teams("warriors VS. Lakers")
        assert team_a == "warriors"
        assert team_b == "lakers"

    # === Edge cases ===

    def test_no_teams_found(self, parser):
        """Return None when no teams found."""
        team_a, team_b = parser.parse_teams("Random text without teams")
        assert team_a is None
        assert team_b is None

    def test_only_one_team(self, parser):
        """Return team and None when only one found."""
        team_a, team_b = parser.parse_teams("Lakers will win tonight")
        assert team_a == "lakers"
        assert team_b is None

    def test_empty_string(self, parser):
        """Handle empty string."""
        team_a, team_b = parser.parse_teams("")
        assert team_a is None
        assert team_b is None

    # === O/U and Spread patterns (should still extract teams) ===

    def test_over_under_pattern(self, parser):
        """O/U pattern should still find teams."""
        team_a, team_b = parser.parse_teams("Mavericks vs. Spurs: O/U 233.5")
        assert team_a == "mavericks"
        assert team_b == "spurs"

    def test_spread_pattern(self, parser):
        """Spread pattern should find the mentioned team."""
        team_a, team_b = parser.parse_teams("Spread: Magic (-8.5)")
        assert team_a == "magic"
        # team_b might be None since only one team mentioned

    # === Full team names ===

    def test_full_team_name_los_angeles_lakers(self, parser):
        """Full city + team name should work."""
        team_a, team_b = parser.parse_teams("Los Angeles Lakers vs. Boston Celtics")
        assert team_a == "lakers"
        assert team_b == "celtics"

    def test_full_team_name_golden_state(self, parser):
        """Golden State Warriors."""
        team_a, team_b = parser.parse_teams("Golden State Warriors vs. LA Clippers")
        assert team_a == "warriors"
        assert team_b == "clippers"


class TestNBATeamParserIntegration:
    """Integration tests with actual Polymarket question formats."""

    @pytest.fixture
    def parser(self):
        return NBATeamParser()

    @pytest.mark.parametrize("question,expected_a,expected_b", [
        ("Mavericks vs. Spurs", "mavericks", "spurs"),
        ("Jazz vs. Magic", "jazz", "magic"),
        ("Hornets vs. Hawks", "hornets", "hawks"),
        ("Nuggets vs. Bulls", "nuggets", "bulls"),
        ("Warriors vs. Lakers", "warriors", "lakers"),
        ("76ers vs. Suns", "sixers", "suns"),
        ("Grizzlies vs. Trail Blazers", "grizzlies", "blazers"),
        ("Cavaliers vs. Kings", "cavaliers", "kings"),
        ("Knicks vs. Celtics", "knicks", "celtics"),
        ("Heat vs. Wizards", "heat", "wizards"),
    ])
    def test_polymarket_questions(self, parser, question, expected_a, expected_b):
        """Test actual Polymarket NBA question formats."""
        team_a, team_b = parser.parse_teams(question)
        assert team_a == expected_a, f"Expected {expected_a}, got {team_a} for '{question}'"
        assert team_b == expected_b, f"Expected {expected_b}, got {team_b} for '{question}'"
