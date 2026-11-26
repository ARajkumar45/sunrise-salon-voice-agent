// Real-browser test of the call page: Chrome opens the page, presses Call, and "speaks"
// a recording through a fake microphone. Proves the page, token, WebRTC audio in both
// directions and the agent work together, without a human.
//
//   npm install puppeteer-core
//   node scripts/browser_call_test.mjs https://HOST/call/sunrise-salon path/to/mic.wav
//
// mic.wav should be: a few seconds of silence, a question, then silence (48 kHz mono).
import puppeteer from "puppeteer-core";

const [url, micFile] = process.argv.slice(2);
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: "new",
  args: [
    "--use-fake-ui-for-media-stream",          // auto-accept the microphone prompt
    "--use-fake-device-for-media-stream",      // use a fake microphone...
    `--use-file-for-fake-audio-capture=${micFile}`,  // ...that plays this file
    "--autoplay-policy=no-user-gesture-required",
  ],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(url, { waitUntil: "networkidle2" });
console.log("page title:      ", await page.title());
console.log("heading:         ", await page.$eval("#title", (el) => el.textContent));
await page.click("#call");
await new Promise((resolve) => setTimeout(resolve, 28000));   // greeting + question + reply
console.log("status line:     ", await page.$eval("#status", (el) => el.textContent));
console.log("timing line:     ", await page.$eval("#timing", (el) => el.textContent));
const audio = await page.$$eval("audio", (els) => els.map((el) => ({ playing: !el.paused, seconds: el.currentTime.toFixed(1) })));
console.log("agent audio:     ", JSON.stringify(audio));
console.log("button now says: ", await page.$eval("#call", (el) => el.textContent));
console.log("page errors:     ", errors.length ? errors : "none");
await page.click("#call");                                       // hang up
await new Promise((resolve) => setTimeout(resolve, 1500));
console.log("after hang up:   ", await page.$eval("#status", (el) => el.textContent));
await browser.close();
