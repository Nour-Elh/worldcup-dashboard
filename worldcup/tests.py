import re

from django.test import TestCase


class DashboardViewTests(TestCase):
    def test_dashboard_renders(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'worldcup/dashboard.html')
        self.assertIn('selected_edition', response.context)
        self.assertContains(response, 'Dashboard')

    def test_dashboard_switches_edition(self):
        response = self.client.get('/', {'edition': '2014'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_edition']['slug'], '2014')
        self.assertContains(response, 'World Cup 2014')
        self.assertContains(response, 'id="stadium-map"', html=False)
        self.assertGreater(len(response.context['venue_map']['markers']), 0)
        self.assertNotContains(response, 'unpkg.com/leaflet')
        self.assertNotContains(response, 'openstreetmap.org')
        self.assertIsNone(re.search(r'left:\s*\d+,\d+%;\s*top:\s*\d+,\d+%;', response.content.decode()))
