import { afterEach, afterAll, beforeAll } from 'vitest'
import { server } from './mock/node'

beforeAll(() => {
  server.listen()
})

afterEach(() => {
  server.resetHandlers()
})

afterAll(() => {
  server.close()
})
