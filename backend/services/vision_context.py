"""将聊天图片理解结果组装为主模型可直接使用的上下文。"""
from dataclasses import dataclass

from backend.services.attachment_service import ChatAttachment, attachment_service
from backend.services.vision_service import vision_service


@dataclass(frozen=True)
class VisionContext:
    display_question: str
    agent_question: str
    summary: str
    analyzed_count: int


class VisionContextService:
    """统一聊天图片的展示文本和主模型上下文格式。"""

    @staticmethod
    def build_display_question(
        attachments: list[ChatAttachment],
        question: str,
    ) -> str:
        parts = []
        for attachment in attachments:
            safe_name = attachment.filename.replace("[", "").replace("]", "")
            parts.append(f"![{safe_name}]({attachment.preview_url})")
        if question.strip():
            parts.append(question.strip())
        if not parts:
            return "请理解这张图片。"
        if not question.strip():
            parts.append("请理解这张图片。")
        return "\n\n".join(parts)

    async def build(
        self,
        *,
        attachments: list[ChatAttachment],
        question: str,
    ) -> VisionContext:
        display_question = self.build_display_question(attachments, question)
        if not attachments:
            return VisionContext(
                display_question=display_question,
                agent_question=question.strip(),
                summary="",
                analyzed_count=0,
            )

        evidence_blocks = []
        for index, attachment in enumerate(attachments, start=1):
            image_content = await attachment_service.read_bytes(attachment)
            result = await vision_service.analyze_image(
                image_content,
                filename=attachment.filename,
                question=question,
            )
            evidence_blocks.append(
                f"[附件 {index}: {attachment.filename}]\n{result.strip()}"
            )

        vision_text = "\n\n".join(evidence_blocks)
        final_question = question.strip() or "请根据图片内容进行说明。"
        agent_question = (
            "以下是系统对用户图片进行视觉分析后提取的事实，请仅将其作为回答依据：\n"
            f"<vision_context>\n{vision_text}\n</vision_context>\n\n"
            f"用户问题：{final_question}"
        )
        summary = vision_text[:800] + ("...(已截断)" if len(vision_text) > 800 else "")
        return VisionContext(
            display_question=display_question,
            agent_question=agent_question,
            summary=summary,
            analyzed_count=len(attachments),
        )


vision_context_service = VisionContextService()
