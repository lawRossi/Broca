import { describe, it, expect } from 'vitest'
import { resolveMediaUrl } from '@/utils/media'

describe('resolveMediaUrl', () => {
  it('prefixes /api for backend local media paths', () => {
    expect(resolveMediaUrl('/files/raw?path=%2Ftmp%2Fa.png')).toBe(
      '/api/files/raw?path=%2Ftmp%2Fa.png'
    )
  })

  it('leaves absolute https cloud urls unchanged', () => {
    const url = 'https://pub.example.com/uploads/a.png'
    expect(resolveMediaUrl(url)).toBe(url)
  })

  it('leaves data and blob urls unchanged', () => {
    expect(resolveMediaUrl('data:image/png;base64,AAAA')).toBe('data:image/png;base64,AAAA')
    expect(resolveMediaUrl('blob:http://x/y')).toBe('blob:http://x/y')
  })

  it('returns empty string for empty input', () => {
    expect(resolveMediaUrl('')).toBe('')
    expect(resolveMediaUrl(null)).toBe('')
    expect(resolveMediaUrl(undefined)).toBe('')
  })

  it('leaves other relative urls unchanged', () => {
    expect(resolveMediaUrl('/assets/logo.png')).toBe('/assets/logo.png')
  })
})
