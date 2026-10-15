import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

import bot
import schemas


class AddProductFlowTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=12345, username="test_admin", full_name="Test Admin")
        self.message = SimpleNamespace(reply_text=AsyncMock())
        self.query = SimpleNamespace(
            answer=AsyncMock(),
            message=self.message,
            from_user=self.user,
        )
        self.update = SimpleNamespace(
            callback_query=self.query,
            effective_user=self.user,
        )

    @staticmethod
    def unauthorized_error():
        request = httpx.Request("POST", "https://api.example.test/products")
        response = httpx.Response(401, request=request)
        return httpx.HTTPStatusError("Unauthorized", request=request, response=response)

    def test_manual_add_keeps_draft_after_auth_error_and_succeeds_on_retry(self):
        product = {
            "name": "Test shoes",
            "price_usd": 44.0,
            "weight_grams": 500,
            "category": "کفش",
            "description": "Test product",
            "photo_paths": ["photos/test.jpg"],
            "original_photo_path": "photos/test.jpg",
        }
        context = SimpleNamespace(user_data={"product": product})
        call_api = AsyncMock(side_effect=self.unauthorized_error())

        async def exercise():
            with patch.object(bot, "call_api", call_api), patch.object(bot, "fire_event"):
                failed_result = await bot.add_confirm_save(self.update, context)
                self.assertEqual(failed_result, bot.CONFIRM)
                self.assertIs(context.user_data["product"], product)
                self.assertIn("ADMIN_API_TOKEN", self.message.reply_text.await_args.args[0])
                self.assertEqual(self.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "confirm_save")

                payload = call_api.await_args.kwargs["data"]
                schemas.ProductCreate(**payload)
                self.assertEqual(payload["created_by_admin_id"], self.user.id)
                self.assertEqual(payload["created_by_admin_username"], self.user.username)
                self.assertEqual(payload["original_photo_path"], "photos/test.jpg")

                call_api.side_effect = None
                call_api.return_value = {"id": 501, "name": "Test shoes", "price_usd": 44.0}
                saved_result = await bot.add_confirm_save(self.update, context)
                self.assertEqual(saved_result, bot.ConversationHandler.END)
                self.assertEqual(context.user_data, {})
                self.assertIn("ID: 501", self.message.reply_text.await_args.args[0])

        asyncio.run(exercise())

    def test_quick_add_keeps_preview_after_auth_error_and_succeeds_on_retry(self):
        preview = {
            "name": "Test bag",
            "price_usd": 23.0,
            "category": "کیف",
            "location": "کانادا",
            "photo_paths": ["photos/test.jpg"],
            "original_photo_path": "photos/test.jpg",
        }
        context = SimpleNamespace(user_data={"product": preview, "quick_preview": preview})
        call_api = AsyncMock(side_effect=self.unauthorized_error())

        async def exercise():
            with patch.object(bot, "call_api", call_api), patch.object(
                bot, "fire_event"
            ), patch.object(bot, "main_menu", return_value="main-menu"):
                failed_result = await bot.quick_add_save(self.update, context)
                self.assertEqual(failed_result, bot.QUICK_CONFIRM)
                self.assertIs(context.user_data["quick_preview"], preview)
                self.assertIn("ADMIN_API_TOKEN", self.message.reply_text.await_args.args[0])
                self.assertEqual(self.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "quick_save")

                payload = call_api.await_args.kwargs["data"]
                schemas.ProductCreate(**payload)
                self.assertEqual(payload["created_by_admin_username"], self.user.username)
                self.assertNotIn("photo_paths", payload)
                self.assertEqual(payload["original_photo_path"], "photos/test.jpg")

                call_api.side_effect = None
                call_api.return_value = {"id": 502}
                saved_result = await bot.quick_add_save(self.update, context)
                self.assertEqual(saved_result, bot.ConversationHandler.END)
                self.assertEqual(context.user_data, {})
                self.assertIn("ID: 502", self.message.reply_text.await_args.args[0])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
