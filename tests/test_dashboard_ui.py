import unittest
from pathlib import Path


class DashboardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (
            Path(__file__).resolve().parents[1] / "tools" / "html_src" / "dashboard.html"
        ).read_text(encoding="utf-8")
        cls.asset = (
            Path(__file__).resolve().parents[1] / "src" / "html" / "dashboard.bin"
        ).read_text(encoding="utf-8")

    def test_data_load_precedes_optional_chart_interactions(self):
        load_position = self.source.index("await load();")
        interaction_position = self.source.index("try{initTooltip()}")
        self.assertLess(load_position, interaction_position)

    def test_dashboard_uses_desk_api_contract(self):
        for endpoint in ("/api/desk/status", "/api/desk/timeline", "/api/desk/daily", "/api/desk/sessions"):
            self.assertIn(endpoint, self.source)

    def test_dashboard_matches_desk_analysis_order_and_labels(self):
        sections = (
            "<span>01</span>總覽",
            "<span>02</span>光線感測器",
            "<span>03</span>近 24 小時狀態軸",
            "<span>04</span>近 30 天書桌前時間",
            "<span>05</span>年度書桌前熱力圖",
            "<span>06</span>每日統計",
            "<span>07</span>最近時段紀錄",
        )
        positions = [self.source.index(section) for section in sections]
        self.assertEqual(positions, sorted(positions))
        for label in ("目前狀態", "今日累計", "目前時段", "今日切換次數", "光線數值", "光線閾值"):
            self.assertIn("<label>{}</label>".format(label), self.source)
        self.assertIn("最後更新：--", self.source)
        self.assertNotIn("ADC / 門檻", self.source)
        self.assertNotIn("資料時間", self.source)
        self.assertIn("年度書桌前熱力圖", self.source)

    def test_generated_asset_keeps_statement_boundary_after_minification(self):
        self.assertIn("renderSessions(sessions);", self.asset)
        self.assertIn("/api/desk/sessions", self.asset)
        self.assertIn("drawHeatmap(da,now,st)", self.asset)
        self.assertIn('id="yearHeatmap"', self.asset)

    def test_dashboard_heatmap_uses_existing_daily_data_and_theme_tokens(self):
        for token in (
            'id="yearHeatmap"',
            "function dateKeyFromDate(d)",
            "function dateFromKey(key)",
            "function heatLevel(sec,hasData)",
            "drawHeatmap(data,now,st)",
            "heatmapCells=[]",
            "--heat-0",
            "--heat-4",
            "最近 365 天",
            "尚無資料",
            "st&&st.current_date",
        ):
            self.assertIn(token, self.source)
        self.assertIn("map[todayKey]={sec:Math.max(0,Number(st&&st.today_seconds)||0),hasData:true}", self.source)

    def test_dashboard_fixes_percentage_metric_alignment_and_canvas_layout(self):
        self.assertIn("Math.min(86400,Number(s)||0))*100/86400", self.source)
        self.assertIn(".metric{text-align:center}", self.source)
        self.assertIn('<canvas id="timeline" width="900" height="80"', self.source)
        self.assertIn("#timeline{height:80px}", self.source)
        self.assertIn("top=18,bh=26", self.source)
        self.assertIn("g.moveTo(x,12);g.lineTo(x,48)", self.source)
        self.assertIn("g.fillText(th+':'+tm,x-15,h-6)", self.source)
        self.assertNotIn("g.fillText('在桌前'", self.source)
        self.assertNotIn("g.fillText('離開'", self.source)

    def test_dashboard_uses_hidpi_canvas_coordinates_and_empty_safe_rendering(self):
        self.assertIn("function fitCanvas(c)", self.source)
        self.assertIn("window.devicePixelRatio||1", self.source)
        self.assertIn("g.setTransform(dpr,0,0,dpr,0,0)", self.source)
        self.assertIn("cssW=rect.width||c.clientWidth||900", self.source)
        self.assertIn(
            "var mx=event.clientX-rect.left,my=event.clientY-rect.top",
            self.source,
        )
        self.assertNotIn("c.width/rect.width", self.source)
        self.assertIn("(data||[]).slice(-30)", self.source)
        self.assertIn("ev=ev||[]", self.source)

    def test_daily_chart_labels_do_not_depend_on_bar_data(self):
        self.assertIn(
            "(index%5===0||index===rows.length-1)&&r.d&&r.d.length>=8",
            self.source,
        )
        self.assertIn("if(sec>0){g.fillStyle=teal", self.source)

    def test_daily_and_session_tables_have_ten_row_pagination(self):
        for element_id in (
            "dailyPrev",
            "dailyNext",
            "dailyPageLabel",
            "sessionsPrev",
            "sessionsNext",
            "sessionsPageLabel",
        ):
            self.assertIn('id="{}"'.format(element_id), self.source)
        self.assertIn("Math.max(1,Math.ceil(tableRows.length/10))", self.source)
        self.assertIn("dailyPage=1,sessionsPage=1", self.source)
        self.assertIn("dailyPage>totalPages", self.source)
        self.assertIn("sessionsPage>totalPages", self.source)
        self.assertIn("dailyPage<=1", self.source)
        self.assertIn("sessionsPage>=totalPages", self.source)
        self.assertIn(".pagination button.ghost", self.source)


if __name__ == "__main__":
    unittest.main()
