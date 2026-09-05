export type AccountMethod = 'phone' | 'email';
export type RegistrationDraft = {
  province: string; city: string; hospital_id: string; hospital_name: string;
  real_name: string; department: string; professional_title: string;
  display_name: string; email: string; phone: string; calling_code: string;
  password: string; confirm_password: string; accepted_terms: boolean; accepted_privacy: boolean;
};
export const emptyRegistration: RegistrationDraft = {
  province: '', city: '', hospital_id: '', hospital_name: '', real_name: '', department: '', professional_title: '',
  display_name: '', email: '', phone: '', calling_code: '+86', password: '', confirm_password: '',
  accepted_terms: false, accepted_privacy: false,
};
export function accountIdentity(method: AccountMethod, draft: Pick<RegistrationDraft, 'email' | 'phone' | 'calling_code'>) {
  return method === 'email' ? { email: draft.email.trim().toLowerCase() } : { phone: draft.calling_code + draft.phone.trim().replace(/[ -]/g, '') };
}
export function registrationError(draft: RegistrationDraft, method: AccountMethod, throughStep = 2): { step: number; message: string } | null {
  const invalid = (value: string, min: number, max: number) => value.trim().length < min || value.trim().length > max || /[\p{C}\u2028\u2029<>]/u.test(value.trim());
  if (!draft.province || invalid(draft.city, 2, 60) || invalid(draft.hospital_name, 2, 120)) return { step: 0, message: '请选择省级地区，并填写完整的城市和医院名称。' };
  if (throughStep < 1) return null;
  if (invalid(draft.real_name, 2, 60) || invalid(draft.department, 2, 60) || invalid(draft.professional_title, 2, 40)) return { step: 1, message: '请填写医生姓名、科室和职称，每项至少2个字符。' };
  if (throughStep < 2) return null;
  if (invalid(draft.display_name, 2, 60)) return { step: 2, message: '昵称需要2至60个字符，不能包含控制字符。' };
  const identity = accountIdentity(method, draft);
  if (method === 'email' && (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(identity.email || '') || draft.email.trim().length > 254)) return { step: 2, message: '请输入有效的邮箱地址。' };
  if (method === 'phone' && !/^(?:\+861[3-9][0-9]{9}|\+852[4-9][0-9]{7}|\+8536[0-9]{7}|\+8869[0-9]{8})$/.test(identity.phone || '')) return { step: 2, message: '请输入有效手机号，并选择正确的区号。' };
  if (draft.password.length < 10 || draft.password.length > 128 || !/\p{L}/u.test(draft.password) || !/\p{N}/u.test(draft.password)) return { step: 2, message: '密码需要10至128位，同时包含字母和数字。' };
  if (draft.password !== draft.confirm_password) return { step: 2, message: '两次输入的密码不一致。' };
  if (!draft.accepted_terms || !draft.accepted_privacy) return { step: 2, message: '请阅读并同意用户协议和隐私说明。' };
  return null;
}
export function registrationPayload(draft: RegistrationDraft, method: AccountMethod) {
  return {
    ...accountIdentity(method, draft), display_name: draft.display_name.trim(), password: draft.password,
    confirm_password: draft.confirm_password, accepted_terms: draft.accepted_terms, accepted_privacy: draft.accepted_privacy,
    doctor_profile: {
      province: draft.province, city: draft.city.trim(), hospital_id: draft.hospital_id || null,
      hospital_name: draft.hospital_name.trim(), real_name: draft.real_name.trim(),
      department: draft.department.trim(), professional_title: draft.professional_title.trim(),
    },
  };
}
