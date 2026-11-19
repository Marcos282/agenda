import json
import re
from xml.etree import ElementTree

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .seo_segments import SEGMENTS


@override_settings(
    DEBUG=False, TENANT_BASE_DOMAIN='tacombinado.net', ALLOWED_HOSTS=['tacombinado.net'],
    PLATFORM_PUBLIC_URL='https://tacombinado.net/',
)
class InstitutionalSEOTests(SimpleTestCase):
    def test_indexable_pages_have_unique_metadata_shared_with_social_cards(self):
        seen_titles, seen_descriptions = set(), set()
        pages = {'home': None, 'manual': None, **{f'agenda-online-{key}': key for key in SEGMENTS}}
        for name, segment in pages.items():
            with self.subTest(name=name):
                path = reverse(name)
                response = self.client.get(path, HTTP_HOST='tacombinado.net', secure=True)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('X-Robots-Tag', response)
                self.assertContains(response, f'<link rel="canonical" href="https://tacombinado.net{path}">', count=1)
                html = response.content.decode()
                title = re.search(r'<title>(.*?)</title>', html)[1]
                description = re.search(r'<meta name="description" content="([^"]+)">', html)[1]
                self.assertNotIn(title, seen_titles)
                self.assertNotIn(description, seen_descriptions)
                seen_titles.add(title)
                seen_descriptions.add(description)
                self.assertEqual(len(re.findall(r'<h1[\s>]', html)), 1)
                self.assertContains(response, f'<meta property="og:title" content="{title}">')
                self.assertContains(response, f'<meta name="twitter:description" content="{description}">')
                schema = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html)[1])
                if segment:
                    self.assertEqual(schema['@type'], 'BreadcrumbList')
                    self.assertContains(response, f'<h1>{SEGMENTS[segment]["title"]}</h1>')
                    self.assertContains(response, f'href="{reverse("registro")}"')
                elif name == 'home':
                    self.assertEqual({entry['@type'] for entry in schema['@graph']},
                                     {'Organization', 'WebSite', 'SoftwareApplication'})
                    for key in SEGMENTS:
                        self.assertContains(response, f'href="{reverse(f"agenda-online-{key}")}"')
                else:
                    self.assertEqual(schema['@type'], 'WebPage')

    def test_institutional_sitemap_and_robots(self):
        response = self.client.get(reverse('sitemap'), HTTP_HOST='tacombinado.net', secure=True)
        root = ElementTree.fromstring(response.content)
        namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
        paths = [reverse(name) for name in ('home', 'manual', 'politica_privacidade')]
        paths.extend(reverse(f'agenda-online-{segment}') for segment in SEGMENTS)
        self.assertCountEqual(
            [node.text for node in root.iter(namespace + 'loc')],
            [f'https://tacombinado.net{path}' for path in paths],
        )
        robots = self.client.get(reverse('robots'), HTTP_HOST='tacombinado.net', secure=True)
        self.assertContains(robots, 'Sitemap: https://tacombinado.net/sitemap.xml')
        panel = self.client.get(reverse('painel:inicio'), HTTP_HOST='tacombinado.net', secure=True)
        self.assertEqual(panel['X-Robots-Tag'], 'noindex, nofollow')
        with override_settings(DEBUG=True):
            dev_robots = self.client.get(reverse('robots'), HTTP_HOST='tacombinado.net', secure=True)
            self.assertContains(dev_robots, 'Disallow: /')
