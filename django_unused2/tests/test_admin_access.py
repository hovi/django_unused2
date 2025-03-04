from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AdminPageTest(TestCase):
    fixtures: list[str] = []

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "admin", "admin@example.com", "pass123"
        )
        self.client.force_login(self.admin_user)
        request = HttpRequest()
        request.user = self.admin_user
        request.method = "GET"
        self.request = request
        self.admin_site = admin.site

    def test_admin_changelist_pages(self):
        for model, model_admin in self.admin_site._registry.items():
            with self.subTest(model=model):
                url = reverse(
                    f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
                )
                response = self.client.get(url)
                # Assert that the changelist page loads successfully
                self.assertEqual(response.status_code, 200, f"Failed at {url}")

    def test_admin_add_pages(self):
        for model, model_admin in self.admin_site._registry.items():
            with self.subTest(model=model):
                if model_admin.has_add_permission(self.request):
                    url = reverse(
                        f"admin:{model._meta.app_label}_{model._meta.model_name}_add"
                    )
                    response = self.client.get(url)
                    self.assertEqual(
                        response.status_code, 200, f"Add page failed at {url}"
                    )

    def test_admin_change_views(self):
        admin_site = admin.site

        for model, model_admin in admin_site._registry.items():
            with self.subTest(model=model.__name__):
                queryset = model_admin.get_queryset(self.request)
                if queryset.exists():
                    instance = queryset.first()
                    with self.subTest(model=model.__name__, pk=instance.pk):
                        change_url = reverse(
                            f"admin:{model._meta.app_label}_{model._meta.model_name}_change",
                            args=(instance.pk,),
                        )
                        response = self.client.get(change_url)
                        self.assertEqual(
                            response.status_code,
                            200,
                            f"Change page for {model.__name__} id {instance.pk} failed to load.",
                        )

    def test_admin_delete_view(self):

        for model, model_admin in self.admin_site._registry.items():
            with self.subTest(model=model.__name__):
                if model_admin.has_delete_permission(self.request):
                    queryset = model_admin.get_queryset(self.request)
                    if (
                        model_admin.has_add_permission(self.request)
                        and queryset.exists()
                    ):
                        instance = queryset.first()
                        with self.subTest(model=model.__name__, pk=instance.pk):
                            delete_url = reverse(
                                f"admin:{model._meta.app_label}_{model._meta.model_name}_delete",
                                args=(instance.pk,),
                            )
                            response = self.client.get(delete_url)
                            self.assertEqual(
                                response.status_code,
                                200,
                                f"Delete page for {model.__name__} id {instance.pk} failed to load.",
                            )
