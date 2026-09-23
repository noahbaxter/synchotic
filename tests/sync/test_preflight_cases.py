"""Every case in the preflight table fires exactly when it should, and stays
quiet on a healthy setup."""
import pytest

from src.sync.preflight import BLOCK, CASES, Setup, WARN, check_setup


def _ok(**overrides) -> Setup:
    """A setup with nothing wrong: rclone connected, a writable library, and
    something turned on."""
    base = dict(mode="rclone", rclone_authed=True, rclone_working=True,
                signed_in=True, token_works=True,
                byoc_configured=False, library_path="/songs",
                library_available=True, library_writable=True,
                library_adopted=True, colliding_folders=(),
                drives_enabled=2, setlists_enabled=10)
    base.update(overrides)
    return Setup(**base)


def _kinds(setup):
    return [c.kind for c in check_setup(setup)]


class TestAHealthySetupSaysNothing:
    def test_nothing_fires_when_everything_is_in_place(self):
        assert check_setup(_ok()) == []

    def test_byoc_fully_configured_is_also_silent(self):
        assert check_setup(_ok(mode="byoc", byoc_configured=True,
                               signed_in=True, rclone_authed=False)) == []


class TestSignInCases:
    def test_rclone_mode_without_rclone(self):
        assert _kinds(_ok(rclone_authed=False, rclone_working=False)) == ["mode_rclone"]

    def test_a_remote_that_exists_but_google_will_not_answer(self):
        """The case that reads as healthy everywhere else in the app and fails
        every large chart on every sync."""
        (concern,) = check_setup(_ok(rclone_authed=True, rclone_working=False))
        assert concern.kind == "mode_rclone_dead"
        assert concern.severity == BLOCK

    def test_a_working_remote_says_nothing(self):
        assert check_setup(_ok(rclone_authed=True, rclone_working=True)) == []

    def test_an_unasked_probe_is_not_a_failure(self):
        """None means the probe did not run, which is every non-rclone mode.
        Reading that as a dead remote would block syncs that are fine."""
        assert check_setup(_ok(rclone_working=None)) == []

    def test_a_saved_sign_in_google_will_not_renew(self):
        (concern,) = check_setup(_ok(mode="byoc", byoc_configured=True,
                                     signed_in=True, token_works=False,
                                     rclone_working=None))
        assert concern.kind == "signin_expired"

    def test_a_sign_in_that_still_works_says_nothing(self):
        assert check_setup(_ok(mode="byoc", byoc_configured=True,
                               signed_in=True, token_works=True,
                               rclone_working=None)) == []

    def test_byoc_without_credentials(self):
        assert _kinds(_ok(mode="byoc", byoc_configured=False)) == ["mode_byoc_creds"]

    def test_byoc_with_credentials_but_never_signed_in(self):
        assert _kinds(_ok(mode="byoc", byoc_configured=True,
                          signed_in=False)) == ["mode_byoc_signin"]

    def test_anonymous_mode_warns_but_does_not_block(self):
        (concern,) = check_setup(_ok(mode="anonymous"))
        assert concern.kind == "mode_anonymous"
        assert concern.severity == WARN

    def test_rclone_being_absent_does_not_matter_in_other_modes(self):
        assert _kinds(_ok(mode="byoc", byoc_configured=True,
                          rclone_authed=False)) == []


class TestLibraryCases:
    def test_no_library_picked_at_all(self):
        """There is no default any more, so this is the first thing a fresh
        install is told, ahead of every other case."""
        found = check_setup(_ok(library_set=False))
        assert [c.kind for c in found] == ["library_unset"]
        assert found[0].severity == BLOCK

    def test_an_unset_library_is_not_also_reported_as_missing(self):
        """Never chosen and not on disk are both true of a fresh install. Two
        rows for one cause reads as two problems."""
        assert _kinds(_ok(library_set=False, library_available=False,
                          library_writable=False)) == ["library_unset"]

    def test_a_library_that_is_not_there(self):
        assert _kinds(_ok(library_available=False)) == ["library_missing"]

    def test_a_library_that_cannot_be_written_to(self):
        assert _kinds(_ok(library_writable=False)) == ["library_readonly"]

    def test_a_missing_library_is_reported_once_not_twice(self):
        """Unwritable is about a folder that is there. Both firing would read
        as two separate problems with one cause."""
        assert _kinds(_ok(library_available=False,
                          library_writable=False)) == ["library_missing"]

    def test_charts_already_here_that_we_did_not_download(self):
        (concern,) = check_setup(_ok(library_adopted=False,
                                     colliding_folders=("Rock Band", "Misc")))
        assert concern.kind == "unowned_library"
        assert "Rock Band, Misc" in concern.detail

    def test_a_library_we_already_sync_into_is_not_flagged(self):
        """The collision is only interesting before the first sync. After that
        those folders are ours, which is the normal state of every install."""
        assert _kinds(_ok(library_adopted=True,
                          colliding_folders=("Rock Band",))) == []

    def test_only_the_first_few_names_are_listed(self):
        (concern,) = check_setup(_ok(
            library_adopted=False,
            colliding_folders=("A", "B", "C", "D", "E")))
        assert "and 2 more" in concern.detail


class TestNothingToDoCases:
    def test_no_drives_turned_on(self):
        assert _kinds(_ok(drives_enabled=0, setlists_enabled=0)) == ["nothing_on"]

    def test_drives_on_but_every_setlist_off(self):
        assert _kinds(_ok(setlists_enabled=0)) == ["no_setlists"]


class TestTheTableItself:
    def test_every_case_carries_a_fix(self):
        """A case with no fix is a dead end, which is the thing this screen
        exists to stop."""
        assert all(fix for *_, fix in CASES)

    def test_every_case_is_a_blocker_or_a_warning(self):
        assert {severity for _, severity, *_ in CASES} <= {BLOCK, WARN}

    def test_kinds_are_unique(self):
        kinds = [kind for kind, *_ in CASES]
        assert len(kinds) == len(set(kinds))

    def test_blockers_are_listed_before_warnings(self):
        found = check_setup(_ok(mode="anonymous", library_available=False))
        assert [c.severity for c in found] == [BLOCK, WARN]

    @pytest.mark.parametrize("kind", [kind for kind, *_ in CASES])
    def test_each_case_can_actually_fire(self, kind):
        """Guards against a predicate that no reachable setup satisfies."""
        triggers = {
            "mode_rclone": dict(rclone_authed=False),
            "mode_rclone_dead": dict(rclone_authed=True, rclone_working=False),
            "signin_expired": dict(mode="byoc", byoc_configured=True,
                                   signed_in=True, token_works=False),
            "mode_byoc_creds": dict(mode="byoc", byoc_configured=False),
            "mode_byoc_signin": dict(mode="byoc", byoc_configured=True,
                                     signed_in=False),
            "library_unset": dict(library_set=False),
            "library_missing": dict(library_available=False),
            "library_readonly": dict(library_writable=False),
            "nothing_on": dict(drives_enabled=0),
            "no_setlists": dict(setlists_enabled=0),
            "mode_anonymous": dict(mode="anonymous"),
            "unowned_library": dict(library_adopted=False,
                                    colliding_folders=("Misc",)),
        }
        assert kind in _kinds(_ok(**triggers[kind]))
