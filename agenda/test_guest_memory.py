from django.test import Client, TestCase, override_settings
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.customer_views import GUEST_COOKIE_NAME


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost'], DEV_PUBLIC_HOST='',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class GuestReservationMemoryTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.host = {'HTTP_HOST':'marcos.localhost'}

    def reserve(self):
        response = self.client.post(self.slots_url(), self.payload(), **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertIn(GUEST_COOKIE_NAME, response.cookies)
        return response

    def test_remembers_service_after_session_is_lost(self):
        response = self.reserve()
        cookie = response.cookies[GUEST_COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(int(cookie['max-age']), 180*24*60*60)
        self.client.cookies.pop('sessionid', None)
        response = self.client.get(reverse('agenda:meus'), **self.host)
        self.assertEqual(response.context['agendamentos'].paginator.count, 1)
        self.assertContains(response, 'Corte')
        self.assertContains(response, 'João')
        self.assertContains(response, '40,00')
        booking = response.context['agendamentos'][0]
        self.assertEqual(self.client.get(reverse('agenda:detalhe', args=[booking.pk]), **self.host).status_code, 200)

    def test_logout_keeps_guest_reservation_cookie(self):
        self.reserve()
        self.client.post(reverse('logout'), **self.host)
        response = self.client.get(reverse('agenda:meus'), **self.host)
        self.assertEqual(response.context['agendamentos'].paginator.count, 1)

    def test_tampering_and_other_tenant_do_not_grant_access(self):
        response = self.reserve()
        value = response.cookies[GUEST_COOKIE_NAME].value
        other = Client()
        other.cookies[GUEST_COOKIE_NAME] = value
        response = other.get(reverse('agenda:meus'), HTTP_HOST='wanessa.localhost')
        self.assertEqual(response.context['agendamentos'].paginator.count, 0)
        other.cookies[GUEST_COOKIE_NAME] = value[:-1]+('A' if value[-1]!='A' else 'B')
        response = other.get(reverse('agenda:meus'), **self.host)
        self.assertEqual(response.context['agendamentos'].paginator.count, 0)
        clean = Client()
        response = clean.get(reverse('agenda:meus'), **self.host)
        self.assertEqual(response.context['agendamentos'].paginator.count, 0)

    def test_existing_session_is_migrated_and_personal_link_restores_access(self):
        response = self.reserve()
        personal_url = response.url
        del self.client.cookies[GUEST_COOKIE_NAME]
        response = self.client.get(reverse('agenda:meus'), **self.host)
        self.assertIn(GUEST_COOKIE_NAME, response.cookies)
        recovered = Client()
        response = recovered.get(personal_url, **self.host)
        self.assertIn(GUEST_COOKIE_NAME, response.cookies)
        recovered.cookies.pop('sessionid', None)
        response = recovered.get(reverse('agenda:meus'), **self.host)
        self.assertEqual(response.context['agendamentos'].paginator.count, 1)

    def test_choose_service_has_my_bookings_button(self):
        self.reserve()
        response = self.client.get(reverse('agenda:escolher_data',args=[self.offer.pk]), **self.host)
        self.assertContains(response, 'Meus agendamentos →')
        self.assertContains(response, reverse('agenda:meus'))
