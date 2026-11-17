/**
 * Tests for the dual-channel upload module (Task 4.2 / Task 4.4).
 *
 * - No cloud storage → POST /files/upload (backend local disk), returns local_path.
 * - Cloud storage configured → S3 direct upload, returns storage_key.
 * - sha256 always computed (crypto.subtle when available, js-sha256 fallback).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { sha256 as jsSha256 } from 'js-sha256'

const mocks = vi.hoisted(() => ({
  getGeneralConfig: vi.fn(),
  uploadBackend: vi.fn(),
}))

vi.mock('@/api/config', () => ({
  default: { getGeneralConfig: mocks.getGeneralConfig },
}))

vi.mock('@/api/files', () => ({
  filesApi: { uploadFile: mocks.uploadBackend },
}))

vi.mock('@aws-sdk/client-s3', () => ({
  S3Client: class {
    async send() {
      return {}
    }
  },
  PutObjectCommand: class {
    constructor(public input: any) {}
  },
}))

/** Re-import the module with fresh internal cache for each test. */
async function loadModule() {
  vi.resetModules()
  return await import('@/utils/upload')
}

beforeEach(() => {
  mocks.getGeneralConfig.mockReset()
  mocks.uploadBackend.mockReset()
})

describe('computeSha256', () => {
  it('matches js-sha256 for known bytes (subtle path)', async () => {
    const bytes = new Uint8Array([0, 1, 2, 3, 255, 254, 128, 42])
    const expected = jsSha256(bytes)
    const { computeSha256FromBuffer } = await loadModule()
    expect(await computeSha256FromBuffer(bytes.buffer)).toBe(expected)
  })

  it('falls back to js-sha256 when crypto.subtle is unavailable', async () => {
    const bytes = new Uint8Array([9, 8, 7, 6, 5, 4, 3, 2, 1])
    const expected = jsSha256(bytes)
    const { computeSha256FromBuffer } = await loadModule()

    const original = crypto.subtle
    Object.defineProperty(crypto, 'subtle', { value: undefined, configurable: true })
    try {
      expect(await computeSha256FromBuffer(bytes.buffer)).toBe(expected)
    } finally {
      Object.defineProperty(crypto, 'subtle', { value: original, configurable: true })
    }
  })
})

describe('uploadFile channel selection', () => {
  it('uses backend upload when no cloud storage is configured', async () => {
    mocks.getGeneralConfig.mockResolvedValue({})
    mocks.uploadBackend.mockResolvedValue({
      name: 'x.png',
      url: '/files/raw?path=%2Fabs%2Fx.png',
      path: '/abs/x.png',
      local_path: '/abs/x.png',
      size: 4,
      type: 'image/png',
      sha256: 'deadbeef',
    })

    const { uploadFile } = await loadModule()
    const file = new File([new Uint8Array([1, 2, 3, 4])], 'x.png', { type: 'image/png' })
    const res = await uploadFile(file)

    expect(mocks.uploadBackend).toHaveBeenCalledTimes(1)
    expect(res.local_path).toBe('/abs/x.png')
    expect(res.sha256).toBe('deadbeef')
    expect(res.storage_key).toBeUndefined()
  })

  it('uses S3 direct upload when cloud storage is configured', async () => {
    mocks.getGeneralConfig.mockResolvedValue({
      storage: {
        backend: 'cloudflare',
        cloudflare_account_id: 'acc',
        cloudflare_access_key_id: 'key',
        cloudflare_secret_access_key: 'secret',
        cloudflare_bucket: 'bucket',
        cloudflare_public_url: 'https://pub.example.com',
      },
    })

    const { uploadFile } = await loadModule()
    const file = new File([new Uint8Array([1, 2, 3, 4])], 'y.png', { type: 'image/png' })
    const res = await uploadFile(file)

    expect(mocks.uploadBackend).not.toHaveBeenCalled()
    expect(res.storage_key).toBeDefined()
    expect(res.storage_key).toBe(res.path)
    expect(res.local_path).toBeUndefined()
    expect(res.url.startsWith('https://pub.example.com/')).toBe(true)
    expect(typeof res.sha256).toBe('string')
    expect(res.sha256).toHaveLength(64)
  })
})
