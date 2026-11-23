"""Film the ScanForge demo page frame by frame (deterministic camera orbit)."""
import math
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8765/"
OUT = Path("/tmp/vid/app")
VW, VH, DSF = 1600, 900, 1.2          # -> 1920x1080 frames

OVERLAY_JS = r"""
(() => {
  const st = document.createElement('style');
  st.textContent = `
  #vc{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:99;display:flex;align-items:center;gap:12px;
      max-width:1100px;padding:14px 22px;border-radius:12px;background:rgba(14,16,20,.9);border:1px solid #2C323C;
      font:500 19px Inter,sans-serif;color:#E6E8EB;box-shadow:0 8px 30px rgba(0,0,0,.45);white-space:nowrap}
  #vc b{font-weight:600;color:#062B27;background:#3CCFBE;border-radius:999px;padding:3px 10px;font-size:14px}
  #vc em{font-style:normal;color:#F2B84B} #vc i{font-style:normal;color:#5EE0CF}
  #vcur{position:fixed;z-index:100;width:26px;height:26px;pointer-events:none;transform:translate(-3px,-2px)}
  #vring{position:fixed;z-index:99;width:36px;height:36px;margin:-18px 0 0 -18px;border:2px solid #3CCFBE;border-radius:50%;pointer-events:none;opacity:0}
  .vhl{outline:2px solid #3CCFBE !important;outline-offset:6px;border-radius:8px}`;
  document.head.appendChild(st);
  const c = document.createElement('div'); c.id = 'vc'; c.style.opacity = 0; document.body.appendChild(c);
  const r = document.createElement('div'); r.id = 'vring'; document.body.appendChild(r);
  const k = document.createElement('div'); k.id = 'vcur'; k.style.opacity = 0;
  k.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2l15 11-7 1.2 4 7.3-2.7 1.4-4-7.4L4 20z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  document.body.appendChild(k);
  window.__v = {
    cap(html){ c.innerHTML = html; c.style.opacity = html ? 1 : 0; },
    cur(x, y, o=1){ k.style.left = x + 'px'; k.style.top = y + 'px'; k.style.opacity = o; },
    ring(x, y, t){ r.style.left = x + 'px'; r.style.top = y + 'px'; r.style.opacity = t < 1 ? 1 - t : 0; r.style.transform = `scale(${0.5 + t})`; },
    orbit(az, el, rad){
      const s = window.__sf, t = s.controls.target;
      s.camera.position.set(t.x + rad * Math.cos(el) * Math.cos(az), t.y + rad * Math.sin(el), t.z + rad * Math.cos(el) * Math.sin(az));
      s.camera.lookAt(t); s.renderer.render(s.scene, s.camera);
    },
    sph(){
      const s = window.__sf, p = s.camera.position.clone().sub(s.controls.target);
      const rad = p.length(); return [Math.atan2(p.z, p.x), Math.asin(p.y / rad), rad];
    }
  };
})();
"""


class Film:
    def __init__(self, page):
        self.pg, self.n, self.last = page, 0, None
        self.cx, self.cy = 1180.0, 640.0

    def shot(self, hold=1):
        path = OUT / f"{self.n:05d}.jpg"
        self.pg.screenshot(path=str(path), type="jpeg", quality=92)
        self.n += 1
        for _ in range(hold - 1):
            shutil.copyfile(path, OUT / f"{self.n:05d}.jpg")
            self.n += 1

    def js(self, code, *args):
        return self.pg.evaluate(code, *args) if args else self.pg.evaluate(code)

    def cap(self, html):
        self.js("h => __v.cap(h)", html)

    def move_to(self, selector, frames=22, orbit=None):
        box = self.pg.locator(selector).first.bounding_box()
        tx, ty = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        sx, sy = self.cx, self.cy
        for i in range(1, frames + 1):
            t = i / frames
            e = t * t * (3 - 2 * t)
            self.cx, self.cy = sx + (tx - sx) * e, sy + (ty - sy) * e
            self.js("([x,y]) => __v.cur(x,y)", [self.cx, self.cy])
            if orbit:
                orbit()
            self.shot()

    def click(self, selector, frames=8, orbit=None, real=True):
        if real:
            self.pg.locator(selector).first.click()
        for i in range(frames):
            self.js("([x,y,t]) => __v.ring(x,y,t)", [self.cx, self.cy, i / frames])
            if orbit:
                orbit()
            self.shot()
        self.js("([x,y]) => __v.ring(x,y,2)", [self.cx, self.cy])


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome",
                              args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"])
        pg = b.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=DSF)
        pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg.route("**/fonts.gstatic.com/**", lambda r: r.abort())
        pg.goto(URL)
        pg.wait_for_function("window.__sf")
        pg.evaluate(OVERLAY_JS)
        pg.evaluate("__sf.controls.enableDamping = false")
        f = Film(pg)

        # A · start page
        f.cap("<b>1</b> Start with a scan: run the sample, or drop your own <i>E57 · LAS · LAZ · PLY</i>")
        f.js("([x,y]) => __v.cur(x,y,1)", [f.cx, f.cy])
        f.shot(hold=50)
        f.move_to("#demoBtn", frames=24)
        f.click("#demoBtn")

        # B · processing
        f.cap("<b>2</b> Processing: clean the cloud, find the floor levels, rebuild the walls")
        held = False
        for _ in range(200):
            text = pg.inner_text("#statusText")
            if text.startswith("Done"):
                break
            if not held and ("Cleaning" in text or "Queued" in text or "Creating" in text):
                f.shot(hold=40)
                held = True
            else:
                f.shot()
        pg.wait_for_function("__sf.groups.model.children.length > 0")
        pg.wait_for_timeout(300)
        f.js("__v.cur(0,0,0)")
        az, el, rad = f.js("__v.sph()")
        state = {"az": az, "el": el}

        def orbit_step(daz):
            def step():
                state["az"] += daz
                f.js("([a,e,r]) => __v.orbit(a,e,r)", [state["az"], state["el"], rad * 0.92])
            return step

        # C · result + slow orbit
        f.cap("<b>3</b> Model rebuilt over the scan in about 2 seconds · grey dots = scan points")
        spin = orbit_step(math.radians(0.55))
        for _ in range(190):
            spin()
            f.shot()

        # D · toggles
        f.cx, f.cy = 1300, 300
        f.js("([x,y]) => __v.cur(x,y,1)", [f.cx, f.cy])
        f.move_to("#tPoints", frames=18, orbit=spin)
        f.click("#tPoints", orbit=spin)
        f.cap("<b>4</b> Model only · <em>amber</em> = thickness assumed (one face scanned) · <i>teal</i> = measured")
        for _ in range(95):
            spin()
            f.shot()
        f.click("#tPoints", frames=6, orbit=spin)
        f.move_to("#tModel", frames=12, orbit=spin)
        f.click("#tModel", orbit=spin)
        f.cap("<b>5</b> Scan only · what the scanner actually saw")
        for _ in range(65):
            spin()
            f.shot()
        f.click("#tModel", frames=8, orbit=spin)
        for _ in range(10):
            spin()
            f.shot()

        # E · results panel
        f.cap("<b>6</b> Every wall listed: length, thickness, and whether it was measured or assumed")
        y_target = pg.evaluate("document.querySelector('#walls').getBoundingClientRect().bottom + window.scrollY - 560")
        for i in range(1, 31):
            t = i / 30
            e = t * t * (3 - 2 * t)
            pg.evaluate(f"window.scrollTo(0, {y_target * e})")
            spin()
            f.shot()
        pg.evaluate("document.querySelector('#walls').classList.add('vhl')")
        f.cx, f.cy = 700, 300
        f.move_to("#walls tbody tr:last-child", frames=22, orbit=spin)
        for _ in range(55):
            spin()
            f.shot()
        pg.evaluate("document.querySelector('#walls').classList.remove('vhl')")
        f.cap("<b>7</b> Download the IFC · opens in Revit, ArchiCAD, Navisworks")
        f.move_to("#ifcLink", frames=18, orbit=spin)
        f.click("#ifcLink", frames=8, orbit=spin, real=False)
        for _ in range(45):
            spin()
            f.shot()
        b.close()
    print("frames", f.n)


if __name__ == "__main__":
    main()
