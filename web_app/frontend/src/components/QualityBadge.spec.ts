import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import QualityBadge from './QualityBadge.vue'

describe('QualityBadge', () => {
  it('uses text in addition to color for warning state', () => {
    const wrapper = mount(QualityBadge, { props: { status: 'warning' } })
    expect(wrapper.text()).toContain('存在风险')
    expect(wrapper.classes()).toContain('quality-badge--warn')
  })
})
