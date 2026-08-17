#!/usr/bin/env python3
"""lite-svg perColor 渐变 id 全文档冲突根治 —— 复现/自测脚本.

目的: 验证 static-site/app.js(或 app.min.js)修复后, 多张 perColor 分段色图渲染进
      同一 document 时渐变 id 全文档唯一、每图 path url(#lwGrad-N) 首匹配=自身渐变、
      逐数据点渲染色=各图自身色函数(对照 docs/lite-svg-grad-id-collision.md §4)。
方法口径: headless Chrome 加载临时组合页(注入多图 _lwSVG), CDP 读取 #out 断言输出。
输入依赖: static-site/app.js(修复后)或 static-site/app.min.js; /Applications/Google Chrome.app。
输出: 断言结果(全 PASS = 修复生效)。
关键参数种子: 4 张图色函数(恐贪5段/情绪分5段/跨市场灰蓝/过拟合绿黄红), 数据点选区分值。
复现命令: python3 docs/scripts/lite-grad-id-collision_test.py
"""
import subprocess, time, json, os, sys, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ASSET = sys.argv[1] if len(sys.argv) > 1 else "app.js"  # 默认测源码, 可传 app.min.js 验产物
ASSET_PATH = os.path.join(ROOT, "static-site", ASSET)
assert os.path.exists(ASSET_PATH), f"missing {ASSET_PATH}"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9341
PORT_HTTP = 8939

TEST_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><div id="out"></div>
<script src="http://localhost:{port}/{asset}"></script>
<script>
(function(){{
var O=document.getElementById("out");
function w(x){{O.textContent=(O.textContent?O.textContent+"\\n":"")+x;}}
function mkChart(name,colorFn,data){{return {{name:name,colorFn:colorFn,data:data,
  svg:_lwSVG({{w:320,h:160,pl:40,pr:16,pt:20,pb:30,boundaryGap:true,xLabels:["a","b","c","d"],ys:[{{min:0,max:100}}],
  series:[{{type:"line",data:data,color:"#409eff",width:4,smooth:true,connectNulls:true,itemColor:colorFn}}]}})}};}}
var fearGreedFn=function(i,v){{if(v==null||isNaN(v))return"#86909c";if(v<=20)return"#1e6fd9";if(v<=40)return"#7fb8e8";if(v<=60)return"#c0c4cc";if(v<=80)return"#e6a23c";return"#e6492e";}};
var sentFn=function(i,v){{if(v==null||isNaN(v))return"#86909c";if(v<=10)return"#1e6fd9";if(v<=30)return"#7fb8e8";if(v<=50)return"#c0c4cc";if(v<=70)return"#e6a23c";return"#e6492e";}};
var crossFn=function(i,v){{if(v==null||isNaN(v))return"#86909c";if(v<=40)return"#c0c4cc";if(v<=80)return"#7fb8e8";return"#1e6fd9";}};
var overFn=function(i,v){{if(v==null||isNaN(v))return"#86909c";if(v<=30)return"#52c41a";if(v<=60)return"#e6a23c";return"#e6492e";}};
var cl=[
  mkChart("fear_greed",fearGreedFn,[10,50,90,25]),
  mkChart("sentiment",sentFn,[5,35,75,15]),
  mkChart("cross_market",crossFn,[20,75,45,35]),
  mkChart("overfit",overFn,[15,45,75,25]),
];
document.body.insertAdjacentHTML("beforeend","<div id=renderHost>"+cl.map(function(c){{return '<svg id="svg-'+c.name+'">'+c.svg+'</svg>';}}).join("")+"</div>");
var allIds=[];cl.forEach(function(c){{var m=c.svg.match(/id="lwGrad-\\d+"/g)||[];c.ids=m.map(function(x){{return x.replace('id="','').replace('"','');}});allIds=allIds.concat(c.ids);}});
var unique=new Set(allIds).size;
w("[A] ids total="+allIds.length+" unique="+unique+" PASS="+(unique===allIds.length&&allIds.length===4)+" ids="+allIds.join(","));
var okB=true;
cl.forEach(function(c){{
  var svgEl=document.getElementById("svg-"+c.name);
  var gid=(svgEl.querySelector("path").getAttribute("stroke").match(/#(lwGrad-\\d+)/)||[])[1];
  var first=document.querySelector('linearGradient[id="'+gid+'"]');
  var firstIsOwn=first&&first.ownerSVGElement===svgEl;
  if(!firstIsOwn)okB=false;
  w("[B] "+c.name+" firstIsOwn="+firstIsOwn);
}});
w("[B] PASS="+okB);
var docOrder=[];
cl.forEach(function(c){{var m=c.svg.match(/<linearGradient[^>]*id="([^"]+)"[^>]*>([\\s\\S]*?)<\\/linearGradient>/);if(m)docOrder.push({{id:m[1],stops:parseStops(m[2])}});}});
function parseStops(body){{var st=[],re=/offset="([\\d.]+)%" stop-color="([^"]+)"/g,mm;while((mm=re.exec(body)))st.push({{o:parseFloat(mm[1]),c:mm[2]}});return st;}}
function docColorAt(gid,v){{var grad=null;for(var i=0;i<docOrder.length;i++){{if(docOrder[i].id===gid){{grad=docOrder[i];break;}}}}if(!grad)return "NOGRAD";var off=(100-v);var c="#000";for(var j=0;j<grad.stops.length;j++){{if(grad.stops[j].o<=off)c=grad.stops[j].c;}}return c;}}
var okC=true;
cl.forEach(function(c){{
  var gid=(document.getElementById("svg-"+c.name).querySelector("path").getAttribute("stroke").match(/#(lwGrad-\\d+)/)||[])[1];
  [1,2].forEach(function(ix){{
    var v=c.data[ix];
    var rendered=docColorAt(gid,v);
    var expected=c.colorFn(0,v);
    var pass=rendered===expected;
    if(!pass)okC=false;
    w("[C] "+c.name+"@v"+v+" rendered="+rendered+" expected="+expected+" PASS="+pass);
  }});
}});
w("[C] PASS="+okC);
w("SUMMARY asset={asset} uniqueIds="+(unique===allIds.length&&allIds.length===4)+" ownRef="+okB+" colors="+okC);
}})();
</script></body></html>
"""


def main():
    # 起本地 http server(static-site)
    http = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT_HTTP),
                             "--directory", os.path.join(ROOT, "static-site")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    # 写临时测试页
    tmp = os.path.join(ROOT, "static-site", "__gradtest_id.html")
    with open(tmp, "w") as f:
        f.write(TEST_HTML.format(port=PORT_HTTP, asset=ASSET))
    try:
        chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                                   f"--remote-debugging-port={PORT}", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        ws_url = None
        for _ in range(40):
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://localhost:{PORT}/json/list", timeout=2) as r:
                    lst = json.load(r)
                if lst and lst[0]:
                    ws_url = lst[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if not ws_url:
            print("FAIL: 无法连接 headless Chrome")
            sys.exit(1)
        # 用 node 驱动 CDP(规避手写 ws 客户端)
        driver = os.path.join(ROOT, "docs", "scripts", "_grad_id_cdp.js")
        with open(driver, "w") as f:
            f.write(f"""
const {{ spawn }} = require('child_process');
const ws = new WebSocket('{ws_url}');
let id=0;const pend={{}};
const send=(method,params={{}})=>new Promise((res)=>{{const i=++id;pend[i]=res;ws.send(JSON.stringify({{id:i,method,params}}));}});
ws.onmessage=(e)=>{{const m=JSON.parse(e.data);if(m.id&&pend[m.id]){{pend[m.id](m.result);delete pend[m.id];}}}};
(async()=>{{
  await new Promise(r=>ws.onopen=r);
  await send("Page.enable");await send("Runtime.enable");
  await send("Page.navigate",{{url:"http://localhost:{PORT_HTTP}/__gradtest_id.html"}});
  await new Promise(r=>setTimeout(r,12000));
  const r=await send("Runtime.evaluate",{{expression:"document.getElementById('out').textContent",returnByValue:true}});
  console.log(r.result.value);
  process.exit(0);
}})().catch(e=>{{console.error(e);process.exit(1);}});
""")
        out = subprocess.run(["node", driver], capture_output=True, text=True, timeout=60)
        print(out.stdout)
        chrome.terminate()
        # 断言(证据: [A] 渐变 id 全文档唯一 / [B] 每图 path 首匹配=自身渐变 / [C] 逐点渲染色=自身色函数)
        text = out.stdout
        ids_ok = re.search(r"\[A\] ids total=4 unique=4 PASS=true", text) is not None
        b_ok = "[B] PASS=true" in text
        c_ok = "[C] PASS=true" in text
        no_fail = "PASS=false" not in text and "SUMMARY" in text
        ok = ids_ok and b_ok and c_ok and no_fail
        print("=== RESULT:", "PASS(修复生效)" if ok else "FAIL(修复未生效)", f"for {ASSET} ===")
        os.remove(driver)
        os.remove(tmp)
        sys.exit(0 if ok else 1)
    finally:
        http.terminate()


if __name__ == "__main__":
    main()
