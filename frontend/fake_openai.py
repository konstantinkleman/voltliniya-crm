import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_POST(self):
        n=int(self.headers["Content-Length"]); body=json.loads(self.rfile.read(n))
        assert self.headers["Authorization"]=="Bearer test-key", "no auth"
        assert body["response_format"]["type"]=="json_object"
        img=[c for c in body["messages"][1]["content"] if c["type"]=="image_url"]
        assert img and img[0]["image_url"]["url"].startswith("data:image/"), "no image"
        cats = body["messages"][1]["content"][0]["text"]
        out={"supplier":"ООО Кабель-Центр","doc_number":"УТ-123","date":"2026-10-13","lines":[
            {"raw":"Кабель ВВГнг(А)-LS 3х2,5 ок(N)-0,66 ГОСТ (бухта 100м)","short":"Кабель ВВГнг-LS 3×2,5","qty":500,"unit":"м","unit_price":86,"total":43000,"category":"Кабель" if "Кабель" in cats else None,"confidence":"high"},
            {"raw":"Коробка распределительная 100x100","short":"Коробка распред. 100×100","qty":5,"unit":"шт","unit_price":110,"total":600,"category":None,"confidence":"high"}]}
        resp=json.dumps({"choices":[{"message":{"content":json.dumps(out,ensure_ascii=False)}}]}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(resp))); self.end_headers(); self.wfile.write(resp)
http.server.HTTPServer(("127.0.0.1",8111),H).serve_forever()
