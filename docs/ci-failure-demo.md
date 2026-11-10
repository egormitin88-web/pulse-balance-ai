# ДЗ PRO, пункт 4: обнаружение и исправление ошибки

Ветка: `feature/schedule-availability`.

## Намеренная ошибка

В `frontend/tests/schedule.test.mjs`, в тесте `availability filter hides full classes across all directions`, ожидаемый результат изменён с `[1, 3]` на `[1, 2, 3]`. При этом тестовое занятие с `id=2` имеет `free_places=0` и должно быть скрыто включённым фильтром.

Изменён только тест. Рабочая логика фильтра не повреждалась; ошибка не объединялась с `main`.

Коммит с ошибкой: [`1c78e86`](https://github.com/egormitin88-web/pulse-balance-ai/commit/1c78e86d946751feab3cb6af08cc72f181566d2c).

## Неуспешная проверка и прочитанный лог

[Запуск GitHub Actions #2 — Failure](https://github.com/egormitin88-web/pulse-balance-ai/actions/runs/42874205187).

- `Frontend tests and build`: Failure, шаг `Test schedule availability filter` завершился с кодом 1.
- `Backend tests`: Success.
- Из пяти frontend-тестов четыре прошли, один упал.
- Сборка интерфейса в этом задании была пропущена после неуспешного теста.

Прочитан именно лог задания GitHub Actions, а не только локальный вывод. Диагностика:

```text
AssertionError [ERR_ASSERTION]: Expected values to be strictly deep-equal
actual: [1, 3]
expected: [1, 2, 3]
at tests/schedule.test.mjs:17:10
```

Причина: ошибочное ожидание теста включает заполненное занятие. Фактический результат соответствует требованию `free_places > 0`.

## Исправление

Ожидание восстановлено на `[1, 3]` отдельным коммитом `Fix intentional CI failure by excluding the fully booked class`. Проверка не отключалась, тест не удалялся, `continue-on-error` не добавлялся.

Перед отправкой исправления локально повторно выполнены `npm test` и `npm run build`: пять тестов прошли, TypeScript и Vite собрали приложение.

После отправки этого коммита workflow автоматически запускается повторно. Результат виден в [GitHub Actions](https://github.com/egormitin88-web/pulse-balance-ai/actions). Ссылка на завершившийся успешный запуск сохраняется в итоговом отчёте и в сообщении о результате этапа.
