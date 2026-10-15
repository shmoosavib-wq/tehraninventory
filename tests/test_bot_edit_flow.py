import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

import bot


class ConfirmEditFlowTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=12345, username="test_admin", full_name="Test Admin")
        self.message = SimpleNamespace(reply_text=AsyncMock())
        self.query = SimpleNamespace(
            answer=AsyncMock(),
            message=self.message,
            from_user=self.user,
        )
        self.update = SimpleNamespace(callback_query=self.query)
        self.context = SimpleNamespace(user_data={
            "editing_product_id": 77,
            "editing_field": "weight_grams",
            "pending_edit_value": 250,
        })

    def test_failed_save_keeps_edit_and_retry_can_succeed(self):
        request = httpx.Request("PUT", "https://api.example.test/products/77")
        response = httpx.Response(401, request=request)
        unauthorized = httpx.HTTPStatusError(
            "Unauthorized", request=request, response=response
        )
        call_api = AsyncMock(side_effect=unauthorized)

        async def exercise():
            with patch.object(bot, "call_api", call_api), patch.object(
                bot, "main_menu", return_value="main-menu"
            ):
                first_result = await bot.confirm_edit_callback(self.update, self.context)
                self.assertEqual(first_result, bot.EDIT_VALUE)
                self.assertEqual(self.context.user_data["editing_product_id"], 77)
                self.assertEqual(self.context.user_data["editing_field"], "weight_grams")
                self.assertEqual(self.context.user_data["pending_edit_value"], 250)
                self.assertIn("ADMIN_API_TOKEN", self.message.reply_text.await_args.args[0])

                call_api.side_effect = None
                call_api.return_value = {"id": 77}
                second_result = await bot.confirm_edit_callback(self.update, self.context)
                self.assertEqual(second_result, bot.ConversationHandler.END)
                self.assertEqual(self.context.user_data, {})
                self.assertIn("با موفقیت", self.message.reply_text.await_args.args[0])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
