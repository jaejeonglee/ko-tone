// hero.html을 1200×400 CSS 픽셀, 2배 해상도(2400×800) PNG로 렌더링한다.
// 사용법: node assets/readme/render.js   (Playwright와 Chromium 필요)
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 400 }, deviceScaleFactor: 2 });
  await page.goto("file://" + path.join(__dirname, "hero.html"));
  await page.evaluate(() => document.fonts.ready); // 웹폰트가 다 받아진 뒤에 찍는다
  await page.screenshot({
    path: path.join(__dirname, "hero.png"),
    clip: { x: 0, y: 0, width: 1200, height: 400 },
    omitBackground: true, // 둥근 모서리 바깥은 투명하게
  });
  await browser.close();
})();
