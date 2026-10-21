module.exports = async ({page, say, pause, app}) => {
  const rows = page.locator("#visitsTable tbody tr");
  const paginator = page.locator("mat-paginator");
  const header = (name) => page.locator("#visitsTable th").filter({hasText: new RegExp(`^\\s*${name}\\s*$`)});
  const rowsAre = (n) => page.waitForFunction(
    (c) => document.querySelectorAll("#visitsTable tbody tr").length === c, n, {timeout: 10000});
  const pickSize = async (size) => {
    await page.locator("mat-paginator mat-select").click();
    await page.getByRole("option", {name: String(size), exact: true}).click();
  };

  await page.goto(`${app}/visits`);
  await rows.first().waitFor();
  await paginator.waitFor();
  await rowsAre(10);
  await say("The visits grid now shows the ten latest visits, one page at a time.", paginator);
  await pause(1500);

  await pickSize(5);
  await rowsAre(5);
  await say("Pages of five rows.", paginator);
  await pause(1200);

  await pickSize(20);
  await rowsAre(20);
  await say("Or twenty.", paginator);
  await pause(1200);

  await pickSize(5);
  await rowsAre(5);
  const next = page.getByRole("button", {name: "Next page"});
  await next.waitFor();
  await next.click();
  await page.waitForURL(/page=2/);
  await say("Next page, and the page number lands in the URL.", paginator);
  await pause(1500);

  const owner = header("Owner");
  await owner.waitFor();
  await owner.click();
  await page.waitForURL(/sort=owner/);
  await say("Every column header sorts. Owner, ascending, back on page one.", owner);
  await pause(1500);

  await owner.click();
  await page.waitForURL(/sort=owner(,|%2C)desc/);
  await say("Click again to reverse it.", owner);
  await pause(1500);

  const pet = header("Pet");
  await pet.click();
  await page.waitForURL(/sort=pet/);
  await say("Same for Pet.", pet);
  await pause(1200);

  await page.reload();
  await rows.first().waitFor();
  await rowsAre(5);
  await header("Pet").waitFor();
  await say("The state lives in the URL, so a reload keeps the size, the page and the sort.", paginator);
  await pause(1500);

  return {ok: true, note: "visits grid: page sizes 5/10/20, next page, sort by Owner/Pet, reload keeps URL state"};
};
