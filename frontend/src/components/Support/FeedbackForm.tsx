import { useMutation } from "@tanstack/react-query"
import { Star } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { ApiError, submitSupportFeedback } from "@/services/supportApi"

type FeedbackFormProps = {
  requestId: string
  onSubmitted?: (requestId: string, rating: number) => void
}

export function FeedbackForm({ requestId, onSubmitted }: FeedbackFormProps) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState("")
  const [done, setDone] = useState(false)

  const mutation = useMutation({
    mutationFn: () =>
      submitSupportFeedback({
        request_id: requestId,
        rating,
        comment: comment.trim() || undefined,
      }),
    onSuccess: () => {
      setDone(true)
      showSuccessToast("Спасибо, отзыв сохранён")
      onSubmitted?.(requestId, rating)
    },
    onError: (error: Error) => {
      // 409 — отзыв на этот запрос уже есть (один отзыв на запрос, решение V7)
      if (error instanceof ApiError && error.status === 409) {
        setDone(true)
        showErrorToast("Вы уже оценивали этот запрос")
        return
      }
      showErrorToast(error.message)
    },
  })

  if (done) {
    return (
      <p className="text-xs text-muted-foreground">
        Спасибо! Отзыв по этому запросу учтён.
      </p>
    )
  }

  return (
    <div className="grid gap-2 rounded-md border bg-muted/20 p-3">
      <p className="text-xs font-medium text-muted-foreground">Оцените ответ</p>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((value) => (
            <button
              key={value}
              type="button"
              aria-label={`Оценка ${value}`}
              onClick={() => setRating(value)}
              className="rounded p-0.5 transition-colors hover:text-primary"
            >
              <Star
                className={
                  value <= rating
                    ? "size-5 fill-primary text-primary"
                    : "size-5 text-muted-foreground"
                }
              />
            </button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">
          {rating ? `${rating} из 5` : "выберите оценку"}
        </span>
      </div>
      <Textarea
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        placeholder="Комментарий (необязательно)"
        rows={2}
      />
      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={rating === 0 || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Отправляем..." : "Отправить отзыв"}
        </Button>
      </div>
    </div>
  )
}
