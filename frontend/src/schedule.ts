type ScheduleEntry = { service_code: string; free_places: number }

export function filterSchedule<T extends ScheduleEntry>(
  items: readonly T[],
  serviceCode: string,
  onlyAvailable: boolean,
): T[] {
  return items.filter(item =>
    (!serviceCode || item.service_code === serviceCode)
    && (!onlyAvailable || item.free_places > 0),
  )
}
