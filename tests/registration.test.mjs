import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { accountIdentity, emptyRegistration, registrationError, registrationPayload } from '../app/auth/registration-form.ts';

const draft = () => ({ ...emptyRegistration, province: '北京市', city: '北京市', hospital_name: '测试医院', real_name: '测试医生',
  department: '放射科', professional_title: '主治医师', display_name: '测试昵称', email: '  DOCTOR@EXAMPLE.COM ', phone: '13800138000',
  password: 'test-pass-2026', confirm_password: 'test-pass-2026', accepted_terms: true, accepted_privacy: true });

test('registration supports either identity without requiring both', () => {
  assert.equal(registrationError({ ...draft(), phone: '' }, 'email'), null);
  assert.equal(registrationError({ ...draft(), email: '' }, 'phone'), null);
  const email = registrationPayload(draft(), 'email');
  const phone = registrationPayload(draft(), 'phone');
  assert.equal(email.email, 'doctor@example.com'); assert.equal('phone' in email, false);
  assert.equal(phone.phone, '+8613800138000'); assert.equal('email' in phone, false);
  assert.equal(phone.doctor_profile.real_name, '测试医生');
  assert.equal(phone.doctor_profile.hospital_id, null);
  assert.equal(phone.confirm_password, phone.password);
});

test('each step checks relevant fields and returns to incomplete earlier steps', () => {
  assert.equal(registrationError(emptyRegistration, 'phone', 0).step, 0);
  const hospital = { ...emptyRegistration, province: '四川省', city: '成都市', hospital_name: '测试医院' };
  assert.equal(registrationError(hospital, 'phone', 0), null);
  assert.equal(registrationError(hospital, 'phone', 1).step, 1);
  assert.equal(registrationError({ ...draft(), hospital_name: '' }, 'email', 2).step, 0);
  assert.equal(registrationError({ ...draft(), real_name: ' ' }, 'email', 2).step, 1);
  for (const changes of [{ password: 'short' }, { confirm_password: 'mismatch' }, { accepted_terms: false },
    { accepted_privacy: false }, { display_name: 'a' }, { display_name: 'ab\ncd' }, { email: 'invalid' }]) {
    assert.equal(registrationError({ ...draft(), ...changes }, 'email').step, 2);
  }
});

test('phone normalization, prefixes and invalid numbers', () => {
  assert.deepEqual(accountIdentity('phone', { ...draft(), phone: '138 0013-8000' }), { phone: '+8613800138000' });
  for (const [calling_code, phone] of [['+86', '13800138000'], ['+852', '51234567'], ['+853', '61234567'], ['+886', '912345678']]) {
    assert.equal(registrationError({ ...draft(), calling_code, phone }, 'phone'), null);
  }
  for (const phone of ['123', '12800138000', '138001380000', '１３８００１３８０００']) {
    assert.equal(registrationError({ ...draft(), phone }, 'phone').step, 2);
  }
});

test('catalogue is explicitly partial and all provincial regions allow manual entry', () => {
  const catalog = JSON.parse(readFileSync(new URL('../config/registration-catalog.json', import.meta.url), 'utf8'));
  assert.equal(new Set(catalog.provinces).size, 34);
  assert.match(catalog.directory_notice, /不是全国完整/);
  for (const hospital of catalog.hospitals) {
    assert.ok(catalog.provinces.includes(hospital.province));
    assert.match(hospital.source_url, /^https:\/\/www\.nhc\.gov\.cn\//);
  }
});

test('page exposes methods and manual fallback without local credential storage', () => {
  const source = readFileSync(new URL('../app/auth/page.tsx', import.meta.url), 'utf8');
  assert.match(source, /手机号.*mode === 'login'/);
  assert.match(source, /邮箱.*mode === 'login'/);
  assert.match(source, /confirm_password/);
  assert.match(source, /fieldset disabled=\{submitting\}/);
  assert.match(source, /mode.*=== 'register'/);
  assert.match(source, /手动填写医院全称/);
  assert.match(source, /未接入短信或邮件验证/);
  assert.match(source, /role="alert"/);
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
  const menu = readFileSync(new URL('../app/agent/account-menu.tsx', import.meta.url), 'utf8');
  assert.match(menu, /user\?\.email \|\| user\?\.phone_masked/);
  assert.match(menu, /DoctorProfileDetails/);
});
