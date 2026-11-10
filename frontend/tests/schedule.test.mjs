import test from 'node:test'
import assert from 'node:assert/strict'
import { filterSchedule } from '../src/schedule.ts'

const classes = Object.freeze([
  Object.freeze({ id: 1, service_code: 'yoga', free_places: 3 }),
  Object.freeze({ id: 2, service_code: 'yoga', free_places: 0 }),
  Object.freeze({ id: 3, service_code: 'boxing', free_places: 5 }),
  Object.freeze({ id: 4, service_code: 'boxing', free_places: 0 }),
])

test('disabled availability filter preserves all classes and their order', () => {
  assert.deepEqual(filterSchedule(classes, '', false).map(item => item.id), [1, 2, 3, 4])
})

test('availability filter hides full classes across all directions', () => {
  assert.deepEqual(filterSchedule(classes, '', true).map(item => item.id), [1, 2, 3])
})

test('direction and availability filters work together', () => {
  assert.deepEqual(filterSchedule(classes, 'yoga', true).map(item => item.id), [1])
  assert.deepEqual(filterSchedule(classes, 'boxing', true).map(item => item.id), [3])
})

test('turning availability off restores full classes in the selected direction', () => {
  filterSchedule(classes, 'yoga', true)
  assert.deepEqual(filterSchedule(classes, 'yoga', false).map(item => item.id), [1, 2])
})

test('empty schedules, missing directions and no available places return an empty list', () => {
  assert.deepEqual(filterSchedule([], '', true), [])
  assert.deepEqual(filterSchedule(classes, 'pool', true), [])
  assert.deepEqual(filterSchedule([{ service_code: 'yoga', free_places: 0 }], '', true), [])
  assert.deepEqual(filterSchedule([{ service_code: 'yoga', free_places: -1 }], '', true), [])
})
