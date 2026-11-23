from playwright.sync_api import sync_playwright
LOGO = '<svg width="64" height="64" viewBox="0 0 28 28"><rect x="2" y="2" width="24" height="24" rx="6" fill="none" stroke="#3CCFBE" stroke-width="2"/><path d="M8 19V9l6 4 6-4v10" fill="none" stroke="#3CCFBE" stroke-width="2" stroke-linejoin="round"/></svg>'
BASE = """<html><body style="margin:0;width:1600px;height:900px;background:#0E1014;color:#E6E8EB;font-family:Inter,sans-serif;
display:flex;flex-direction:column;justify-content:center;padding:0 140px;box-sizing:border-box;gap:28px">{}</body></html>"""
TITLE = BASE.format(f"""
<div style="display:flex;align-items:center;gap:22px">{LOGO}<span style="font-size:76px;font-weight:600;letter-spacing:-1.5px">ScanForge</span></div>
<div style="font-size:40px;font-weight:500;line-height:1.3">LiDAR scans + 360 video <span style="color:#3CCFBE">→</span> BIM and Revit models</div>
<div style="font-size:24px;color:#9BA3AF">v0.1 demo · sample room scan · walls rebuilt automatically, exported to IFC</div>
<div style="display:flex;gap:12px;margin-top:10px">
  <span style="padding:8px 16px;border-radius:999px;border:1px solid #24514B;background:#1B2A2A;color:#9AF0E4;font-size:18px">Point cloud in</span>
  <span style="padding:8px 16px;border-radius:999px;border:1px solid #2C323C;color:#C9CED6;font-size:18px">Levels · walls · thickness</span>
  <span style="padding:8px 16px;border-radius:999px;border:1px solid #3A3F73;background:#1D2040;color:#C3CBFF;font-size:18px">IFC out</span>
</div>""")
ROW = '<div style="display:flex;align-items:center;gap:16px;font-size:28px"><span style="width:12px;height:12px;border-radius:50%;background:{c}"></span>{t}</div>'
END = BASE.format(f"""
<div style="font-size:24px;color:#9BA3AF;letter-spacing:.5px">WORKING TODAY</div>
{ROW.format(c='#3CCFBE', t='Scanner and iPhone point clouds → levels, walls, thickness → IFC')}
<div style="font-size:24px;color:#9BA3AF;letter-spacing:.5px;margin-top:18px">NEXT</div>
{ROW.format(c='#F2B84B', t='360 video frames lined up with the scan · doors and windows')}
{ROW.format(c='#F2B84B', t='Lights, pipes, ducts and wiring (MEP) · native Revit model via MCP')}
<div style="display:flex;align-items:center;gap:16px;margin-top:40px">{LOGO.replace('64','40')}<span style="font-size:26px;color:#9AF0E4">github.com/siddharthproffessional/scanforge</span></div>""")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
    for name, html in [("title", TITLE), ("end", END)]:
        pg.set_content(html); pg.screenshot(path=f"/tmp/vid/{name}.png")
    b.close()
print("ok")
