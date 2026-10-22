// Film of "Link Visit with Vet" (#37): owner page, book with/without vet, edit/clear, all visits.
module.exports = async ({page, say, pause, app}) => {
  const missed = [];
  const visited = [];
  const screen = async (name, fn) => {
    try { await fn(); visited.push(name); }
    catch (e) { missed.push(`${name} (${e.message.split("\n")[0]})`); }
  };
  const stamp = Date.now();
  const withVet = `Dental follow-up ${stamp}`;
  const noVet = `Quick look ${stamp}`;
  const firstPet = () => page.locator("app-pet-list").first();
  const row = (d) => firstPet().locator("app-visit-list tr").filter({hasText: d});
  const book = async (description, vetLabel) => {
    await firstPet().locator('button:has-text("Add Visit")').click();
    await page.locator('h2:has-text("New Visit")').waitFor();
    await page.locator('input[name="date"]').fill("2026-06-01");
    await page.locator("input#description").fill(description);
    if (vetLabel) await page.locator("select#vet").selectOption({label: vetLabel});
    return page.locator("select#vet");
  };
  const submitAdd = async () => {
    await page.locator('button[type="submit"]:has-text("Add Visit")').click();
    await page.locator('h2:has-text("Owner Information")').waitFor();
  };

  await screen("/owners/3 (visits with and without a vet)", async () => {
    await page.goto(`${app}/owners/3`);
    await page.locator('h2:has-text("Owner Information")').waitFor();
    const header = page.locator("app-visit-list th").filter({hasText: /^Vet$/}).first();
    await header.waitFor();
    await say("The owner's page now has a Vet column on every visit.", header);
    const named = page.locator("td.visit-vet").filter({hasNotText: "No vet"}).first();
    await named.waitFor();
    await say("A visit shows the vet who attended it.", named);
    const none = page.locator("td.visit-vet").filter({hasText: "No vet"}).first();
    await none.waitFor();
    await say("A visit with no vet reads No vet, never blank.", none);
    await pause(1000);
  });

  await screen("/owners/3 -> New Visit (choose a vet)", async () => {
    const vet = await book(withVet, null);
    await vet.waitFor();
    await say("Booking a visit has a new optional Vet field, empty by default.", vet);
    const first = await vet.locator('option:not([value=""])').first().textContent();
    await vet.selectOption({label: first.trim()});
    await say("Here a vet is chosen.", vet);
    await submitAdd();
    const cell = row(withVet).locator("td.visit-vet");
    await cell.waitFor();
    await say("The new visit lists the chosen vet.", cell);
  });

  await screen("/owners/3 -> New Visit (no vet)", async () => {
    const vet = await book(noVet, null);
    await vet.waitFor();
    await say("Leaving the vet empty is allowed.", vet);
    await submitAdd();
    const cell = row(noVet).locator("td.visit-vet");
    await cell.filter({hasText: "No vet"}).waitFor();
    await say("It is saved and reads No vet.", cell);
  });

  await screen("Edit Visit (change then clear the vet)", async () => {
    await row(withVet).locator('button:has-text("Edit Visit")').click();
    await page.locator('h2:has-text("Edit Visit")').waitFor();
    const vet = page.locator("select#vet");
    await vet.waitFor();
    await say("Editing a visit can change the vet.", vet);
    const options = await vet.locator("option").allTextContents();
    const other = options.map(o => o.trim()).filter(o => o && o !== "-- none --").pop();
    await vet.selectOption({label: other});
    await page.locator('button:has-text("Update Visit")').click();
    await page.locator('h2:has-text("Owner Information")').waitFor();
    await row(withVet).locator("td.visit-vet").filter({hasText: other}).waitFor();

    await row(withVet).locator('button:has-text("Edit Visit")').click();
    await page.locator('h2:has-text("Edit Visit")').waitFor();
    await vet.selectOption({label: "-- none --"});
    await say("Or remove it: choosing none clears it.", vet);
    await page.locator('button:has-text("Update Visit")').click();
    await page.locator('h2:has-text("Owner Information")').waitFor();
    const cell = row(withVet).locator("td.visit-vet");
    await cell.filter({hasText: "No vet"}).waitFor();
    await say("Cleared, and it persisted as No vet.", cell);
  });

  await screen("/visits (all visits)", async () => {
    await page.goto(`${app}/visits`);
    const header = page.locator("#visitsTable th").filter({hasText: /^Vet$/});
    await header.waitFor();
    await say("The all-visits screen carries the same Vet column.", header);
    const named = page.locator("#visitsTable td.visit-vet").filter({hasNotText: "No vet"}).first();
    await named.waitFor();
    await say("Vet names and No vet appear here too.", named);
    await pause(1000);
  });

  return {
    ok: missed.length === 0,
    note: `${visited.length}/5 screens filmed` + (missed.length ? ` | FAILED to reach: ${missed.join("; ")}` : ""),
  };
};
