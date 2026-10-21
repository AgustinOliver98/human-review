"""DB fixture colours and the fixture each E2E test starts from (hrbuild/shared/fixtures.py)."""
import json
import subprocess
from pathlib import Path

from hrbuild.shared import fixtures as fx

GLUE = """import {Given, When} from '@cucumber/cucumber';
// a comment that says seed must not count
Given('the clinic has these owners', async function () {
  expect(found, 'is the DB seeded by Flyway?').toBeTruthy();
});
Given('a pet born on {word}', async function (d) { await axios.post('/owners', {}); });
Given('the green household', async function () { await post('/__reset/green'); });
When('I search owners for {string}', async function (s) {});
"""

FEATURE = """Feature: owners
  Background:
    Given the clinic has these owners

  Scenario: Search
    When I search owners for "Pot"

  @fixture:green
  Scenario: Tagged
    When I search owners for "x"
"""

OWN_DATA = """Feature: own
  Background:
    Given a pet born on 2020-01-01

  Scenario: Makes its own rows
    When I search owners for "a"

  Scenario: Loads green itself
    Given the green household
"""

SPEC = """import {test} from './support/trace-fixture';
import * as dsl from './my.dsl';

test('loads green through the DSL', async () => {
  await dsl.owner();
});
"""

DSL = """// the seed's owner 1
export async function owner() { await post('/__reset/green'); }
"""

OWN_SPEC = """import {test} from './support/trace-fixture';
// Mentions the seed only in a comment.
test('creates its own owner', async () => {
  await axios.post('/owners', {});
});
test('asks for blue explicitly', async () => {
  await loadFixture('blue');
});
"""


def repo(tmp_path: Path, colours=None) -> Path:
    files = {
        "be/db/fixtures/green.sql": "-- green",
        "be/db/fixtures/blue.sql": "-- blue",
        "e2e/src/owners.feature": FEATURE,
        "e2e/src/own.feature": OWN_DATA,
        "e2e/src/owners.glue.ts": GLUE,
        "e2e/src/a.spec.ts": SPEC,
        "e2e/src/my.dsl.ts": DSL,
        "e2e/src/b.spec.ts": OWN_SPEC,
    }
    if colours is not None:
        files["be/db/fixtures/fixture-colors.json"] = json.dumps(colours)
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def test_an_unconfigured_fixture_wears_the_colour_its_name_hashes_to(tmp_path):
    reg = fx.fixture_colors(repo(tmp_path))
    assert reg["seed"] == fx.FIXTURE_SEED
    assert reg["colors"] == {n: fx.fixture_hue(n, fx.FIXTURE_PALETTE) for n in ("blue", "green")}


def test_the_hash_is_stable_across_processes():
    # `hash()` would differ per run (PYTHONHASHSEED); fixtures.js mirrors this arithmetic.
    h = 0
    for c in "minimal":
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    assert fx.fixture_hue("minimal", fx.FIXTURE_PALETTE) == fx.FIXTURE_PALETTE[h % 7]


def test_configured_colour_wins_and_the_palette_skips_it(tmp_path):
    reg = fx.fixture_colors(repo(tmp_path, {"green": fx.FIXTURE_PALETTE[0], "seed": "#777777"}))
    assert reg["seed"] == "#777777"
    assert reg["colors"]["green"] == fx.FIXTURE_PALETTE[0]
    assert reg["colors"]["blue"] == fx.fixture_hue("blue", fx.FIXTURE_PALETTE[1:])


def test_a_colour_that_is_not_one_is_ignored(tmp_path):
    reg = fx.fixture_colors(repo(tmp_path, {"green": "red;}</style><script>"}))
    assert reg["colors"]["green"] in fx.FIXTURE_PALETTE


def test_each_test_starts_from_what_its_code_says(tmp_path):
    tests = fx.fixtures_by_test(repo(tmp_path))
    assert tests["e2e/src/owners.feature:9"] == "green"   # a tag on the scenario
    # A scenario whose steps load the fixture through the reset endpoint.
    assert tests["e2e/src/own.feature:8"] == "green"
    # Through an imported DSL, whose code loads it.
    assert tests["e2e/src/a.spec.ts:4"] == "green"
    assert tests["e2e/src/b.spec.ts:6"] == "blue"


def test_a_test_that_declares_no_fixture_starts_empty_and_gets_no_dot(tmp_path):
    """Victor, 21 Oct 2026: a test that does not use a DB fixture starts on an empty
    database. Leaning on seeded rows without saying so is not read as the seed any more —
    the Background below asserts "is the DB seeded by Flyway?" and still gets nothing."""
    reg = fx.fixture_registry(repo(tmp_path))
    for k in ("e2e/src/owners.feature:5", "e2e/src/own.feature:5", "e2e/src/b.spec.ts:3"):
        assert k not in reg["tests"], k
    assert set(reg) == {"seed", "colors", "palette", "tests"}, "no hollow or dashed marks"


def test_a_feature_tag_and_a_default_name_the_seed(tmp_path):
    root = repo(tmp_path)
    (root / "e2e/src/all.feature").write_text(
        "@fixture:default\nFeature: all\n\n  Scenario: one\n    When I search owners for \"a\"\n\n"
        "  @fixture:green\n  Scenario: two\n    When I search owners for \"b\"\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    tests = fx.fixtures_by_test(root)
    assert tests["e2e/src/all.feature:4"] == "seed"
    assert tests["e2e/src/all.feature:8"] == "green"       # the scenario's own tag wins


USE_SPEC = """import {test} from './support/trace-fixture';
test.use({dbFixture: 'default'});

test('on the file default', async () => {});

test.describe('green ones', () => {
  test.use({dbFixture: 'green', viewport: {width: 1, height: 1}});
  test('on green', async () => {});
  test.describe('inner', () => {
    test.use({viewport: {width: 2, height: 2}});
    test('still green', async () => {});
  });
});
"""

SCOPED_SPEC = """import {test} from './support/trace-fixture';
test('empty', async () => {});
test.describe('seeded', () => {
  test.use({dbFixture: 'default'});
  test('on the seed', async () => {});
});
test('empty again', async () => {});
"""


def test_a_playwright_dbfixture_option_is_read_in_the_scope_it_is_used_in(tmp_path):
    root = repo(tmp_path)
    (root / "e2e/src/use.spec.ts").write_text(USE_SPEC)
    (root / "e2e/src/scoped.spec.ts").write_text(SCOPED_SPEC)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    tests = fx.fixtures_by_test(root)
    assert tests["e2e/src/use.spec.ts:4"] == "seed"
    assert tests["e2e/src/use.spec.ts:8"] == "green"        # the describe's own wins
    assert tests["e2e/src/use.spec.ts:11"] == "green"       # a use naming no fixture is skipped
    assert tests["e2e/src/scoped.spec.ts:5"] == "seed"
    assert "e2e/src/scoped.spec.ts:2" not in tests and "e2e/src/scoped.spec.ts:7" not in tests


HOOKS = """package x.functional;
import io.cucumber.java.Before;
public class DatabaseHooks {
    @Before
    public void reset() {
        jdbc.execute("TRUNCATE TABLE visits, pets, owners RESTART IDENTITY CASCADE");
    }
}
"""


def test_a_jvm_scenario_starts_on_what_its_flyway_loads_unless_a_hook_empties_it(tmp_path):
    root = repo(tmp_path)
    feature = ("Feature: a\n  Scenario: one\n    Given x\n\n"
               "  @fixture:green\n  Scenario: two\n    Given y\n")
    for name, text in {"api/pom.xml": "<project/>",
                       "api/src/main/resources/application.properties":
                           "spring.flyway.locations=classpath:db/migration,classpath:db/seed\n",
                       "api/src/test/resources/features/a.feature": feature,
                       "hooked/pom.xml": "<project/>",
                       "hooked/src/main/resources/application.properties":
                           "spring.flyway.locations=classpath:db/migration,classpath:db/seed\n",
                       "hooked/src/test/java/x/functional/DatabaseHooks.java": HOOKS,
                       "hooked/src/test/resources/features/a.feature": feature}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    tests = fx.fixture_registry(root)["tests"]
    assert tests["api/src/test/resources/features/a.feature:2"] == "seed"
    assert tests["api/src/test/resources/features/a.feature:6"] == "green"
    # Truncated before each scenario: it starts empty, so no dot — and the hook is its
    # module's alone.
    assert "hooked/src/test/resources/features/a.feature:2" not in tests
    assert tests["hooked/src/test/resources/features/a.feature:6"] == "green"
    assert fx.fixtures_emptied(root) == {"hooked/src/test/resources/features/a.feature:2":
                                         {"tables": ["visits", "pets", "owners"], "hook": "DatabaseHooks"}}


def test_registry_block_is_script_safe_and_absent_without_fixtures(tmp_path):
    block = fx.render_fixture_registry(repo(tmp_path))
    assert block.startswith('<script type="application/json" id="hr-fixtures">')
    assert "</" not in block[len('<script'):-len("</script>")]
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    assert fx.render_fixture_registry(empty) == ""


def test_the_script_words_the_tip_like_the_demo_bar_and_opens_the_dataset():
    js = (Path(fx.__file__).resolve().parent.parent / "assets" / "fixtures.js").read_text()
    assert "'DB Fixture: ' + (name === 'seed' ? 'Default' : name)" in js
    assert "window.hrOpenDataset" in js
    assert "MutationObserver" in js
    assert "fx-free" not in js and "fx-empty" not in js, "no dot is how a test says it starts empty"


SPRING_TEST = """package x.rest;

import org.junit.jupiter.api.Test;
import org.springframework.test.context.jdbc.Sql;

@SpringBootTest
@AutoConfigureEmbeddedDatabase(provider = ZONKY)
@Transactional
class VisitTest {
    @Autowired Repo repo;

    @Test
    void makesItsOwnRows() {
        repo.save(new Owner());
    }

    @Test
    void readsTheSeededOwner() {
        assertThat(repo.findAll()).as("the seeded owners").isNotEmpty();
    }

    // a comment that says seed must not count
    @Test
    @Sql({"/db/fixtures/green.sql"
    })
    void startsOnGreen() {
        repo.findAll();
    }

    @Test
    @Sql("/somewhere/else.sql")
    void loadsAScriptThatIsNoFixture() {
    }
}
"""

PLAIN_TEST = """package x;
class MathTest {
    @Test
    void adds() { assertEquals(2, 1 + 1); }
}
"""


def _jvm_repo(tmp_path: Path, props: str) -> Path:
    root = repo(tmp_path)
    for name, text in {
            "api/src/main/resources/application.properties": props,
            "api/src/main/resources/db/migration/V1__init.sql": "-- schema",
            "api/src/main/resources/db/seed/R__seed.sql": "-- seed rows",
            "api/src/test/java/x/rest/VisitTest.java": SPRING_TEST,
            "api/src/test/java/x/MathTest.java": PLAIN_TEST}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


def test_a_spring_test_on_a_flyway_with_the_seed_starts_on_it(tmp_path):
    """Victor, 19 Oct 2026: API rows never showed a fixture dot. A Spring test on a Flyway
    DB whose locations include the seed starts from it — read off the configuration, for
    every test, whatever its code mentions; `@Sql` of a fixture names that one; a test with
    no Spring context touches no DB. Keyed by the method's declaration line, as testcov keys
    the Tests tab's rows."""
    root = _jvm_repo(tmp_path, "spring.flyway.locations=classpath:db/migration,classpath:db/seed\n")
    tests = fx.fixture_registry(root)["tests"]
    f = "api/src/test/java/x/rest/VisitTest.java"
    assert tests[f"{f}:18"] == "seed" and tests[f"{f}:13"] == "seed"
    assert tests[f"{f}:26"] == "green"                       # @Sql of a fixture
    assert f"{f}:32" not in tests                            # not ours to name
    assert not any(k.startswith("api/src/test/java/x/MathTest") for k in tests)


def test_a_spring_test_on_a_flyway_without_the_seed_starts_empty(tmp_path):
    root = _jvm_repo(tmp_path, "spring.flyway.locations=classpath:db/migration\n")
    tests = fx.fixture_registry(root)["tests"]
    f = "api/src/test/java/x/rest/VisitTest.java"
    assert f"{f}:18" not in tests and f"{f}:13" not in tests
    assert tests[f"{f}:26"] == "green"                       # its own @Sql still says so


DECLARING_TEST = """package x.rest;

@SpringBootTest
@AutoConfigureEmbeddedDatabase(provider = ZONKY)
class OwnerTest {
    @Test
    void startsEmpty() {}

    @Test
    @DefaultFixture // reads Kevin
    void readsTheSeed() {}

    @Test
    @Sql("classpath:db/seed/R__seed.sql")
    void loadsTheSeedItself() {}
}
"""

DEFAULT_FIXTURE = """package x;

import org.springframework.test.context.jdbc.Sql;

/** The seed, declared. */
@Retention(RetentionPolicy.RUNTIME)
@Sql("classpath:db/seed/R__seed.sql")
public @interface DefaultFixture {
}
"""


def test_tests_config_without_the_seed_and_a_declared_default(tmp_path):
    """Petclinic since 21 Oct 2026: the main config loads the seed, the tests'
    `config/application.properties` drops it, and a test that reads seeded rows says
    `@DefaultFixture` — an annotation of the module's own, carrying `@Sql` of the seed."""
    root = _jvm_repo(tmp_path, "spring.flyway.locations=classpath:db/migration,classpath:db/seed\n")
    for name, text in {
            "api/src/test/resources/config/application.properties":
                "spring.flyway.locations=classpath:db/migration,classpath:db/reference\n",
            "api/src/test/java/x/DefaultFixture.java": DEFAULT_FIXTURE,
            "api/src/test/java/x/rest/OwnerTest.java": DECLARING_TEST}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    tests = fx.fixture_registry(root)["tests"]
    f = "api/src/test/java/x/rest/OwnerTest.java"
    assert f"{f}:7" not in tests                             # declares nothing: empty
    assert tests[f"{f}:11"] == "seed"                        # @DefaultFixture
    assert tests[f"{f}:15"] == "seed"                        # @Sql of the seed's own file
    assert f"api/src/test/java/x/rest/VisitTest.java:13" not in tests
