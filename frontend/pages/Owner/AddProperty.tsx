
import React, { useState, useRef, useEffect } from 'react';
import { Card, Input, Button } from '../../components/UI';
import { propertiesApi, emitPropertiesChanged, setContextMode } from '../../services/api';
import { UserSession } from '../../types';

interface Props {
  user: UserSession | null;
  navigate: (v: string) => void;
  setLoading: (l: boolean) => void;
  notify: (t: 'success' | 'error', m: string) => void;
}

const ALLOWED_PROOF_TYPES = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
const MAX_PROOF_SIZE = 10 * 1024 * 1024; // 10MB
const STEP_LABELS = ['Location', 'Details', 'Proof'];
const TOTAL_STEPS = 3;

function isAllowedProofFile(file: File): boolean {
  const ok = ALLOWED_PROOF_TYPES.includes(file.type) && file.size <= MAX_PROOF_SIZE;
  return ok;
}

const AddProperty: React.FC<Props> = ({ user, navigate, setLoading, notify }) => {
  const [step, setStep] = useState(1);
  const [proofFile, setProofFile] = useState<File | null>(null);
  const proofInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState({
    property_name: '',
    street_address: '',
    city: '',
    state: '',
    zip_code: '',
    country: 'USA',
    property_type: 'house',
    bedrooms: '1',
    unit_count: '',
    is_primary_residence: false,
    primary_residence_unit: '' as string,  // For multi-unit: '1', '2', ... or ''
    proof_type: 'deed',
  });

  const isMultiUnitType = ['apartment', 'duplex', 'triplex', 'quadplex'].includes(formData.property_type);
  const defaultUnitCount: Record<string, string> = { duplex: '2', triplex: '3', quadplex: '4' };

  // Property registration requires Business mode (owner portfolio action)
  useEffect(() => {
    setContextMode('business');
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (step < TOTAL_STEPS) {
      setStep(step + 1);
      return;
    }

    if (!proofFile) {
      notify('error', 'Please upload proof of ownership (PDF or image) in the Proof step before finishing.');
      return;
    }

    if (isMultiUnitType) {
      const uc = parseInt(formData.unit_count, 10);
      if (!formData.unit_count.trim() || isNaN(uc) || uc < 1) {
        notify('error', 'Please enter a valid number of units (at least 1).');
        return;
      }
    }

    setLoading(true);
    try {
      const payload = {
        property_name: formData.property_name || undefined,
        street_address: formData.street_address,
        city: formData.city,
        state: formData.state,
        zip_code: formData.zip_code || undefined,
        country: formData.country,
        property_type: formData.property_type,
        bedrooms: formData.bedrooms,
        is_primary_residence: formData.is_primary_residence,
      };
      if (isMultiUnitType && formData.unit_count) {
        const uc = parseInt(formData.unit_count, 10);
        if (!isNaN(uc) && uc > 0) (payload as { unit_count?: number }).unit_count = uc;
      }
      if (isMultiUnitType && formData.primary_residence_unit) {
        const pu = parseInt(formData.primary_residence_unit, 10);
        if (!isNaN(pu) && pu >= 1) (payload as { primary_residence_unit?: number }).primary_residence_unit = pu;
      }
      const prop = await propertiesApi.add(payload);
      await propertiesApi.uploadOwnershipProof(prop.id, formData.proof_type, proofFile);
      setLoading(false);
      emitPropertiesChanged();
      notify('success', 'Property added.');
      navigate(`property/${prop.id}`);
    } catch (err) {
      setLoading(false);
      notify('error', (err as Error)?.message || 'Failed to add property.');
    }
  };

  const propertyTypes = [
    { id: 'house', name: 'House', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { id: 'apartment', name: 'Apartment', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'condo', name: 'Condo', icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z' },
    { id: 'townhouse', name: 'Townhouse', icon: 'M3 21h18M3 7h18M5 3h14a2 2 0 012 2v16H3V5a2 2 0 012-2z' },
    { id: 'duplex', name: 'Duplex', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'triplex', name: 'Triplex', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
    { id: 'quadplex', name: 'Quadplex', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
  ];

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <button onClick={() => navigate('dashboard')} className="flex items-center gap-2 text-slate-600 hover:text-slate-800 mb-8 font-bold text-sm uppercase tracking-widest transition-colors">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7"></path></svg>
        Back to Dashboard
      </button>

      <div className="mb-12">
        <div className="flex items-center justify-between mb-4">
          {STEP_LABELS.map((s, i) => (
            <div key={s} className="flex flex-col items-center gap-2 relative z-10">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-500 ${step > i + 1 ? 'bg-green-500 text-white' : step === i + 1 ? 'bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] scale-110' : 'bg-slate-200 text-slate-500'}`}>
                {step > i + 1 ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>
                ) : i + 1}
              </div>
              <span className={`text-xs uppercase tracking-widest font-bold ${step === i + 1 ? 'text-blue-600' : 'text-slate-500'}`}>{s}</span>
            </div>
          ))}
        </div>
        <div className="h-1 bg-slate-200 w-full absolute -z-0 max-w-4xl rounded-full translate-y-[-44px]">
          <div className="h-full bg-gradient-to-r from-blue-600 to-green-500 transition-all duration-700 rounded-full" style={{ width: `${((step - 1) / Math.max(1, TOTAL_STEPS - 1)) * 100}%` }}></div>
        </div>
      </div>

      <Card className="p-10 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-blue-600/5 blur-[80px] rounded-full pointer-events-none"></div>

        <form onSubmit={handleSubmit}>
          {step === 1 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h2 className="text-3xl font-bold text-slate-800 mb-2">Property Location</h2>
              <p className="text-slate-500 mb-8">Tell us where the property is located to apply the correct jurisdiction logic.</p>
              <div className="grid md:grid-cols-2 gap-6">
                <div className="md:col-span-2">
                  <Input label="Property Label (e.g., 'Miami Beach Condo')" name="property_name" value={formData.property_name} onChange={e => setFormData({...formData, property_name: e.target.value})} placeholder="Give this property a nickname" required />
                </div>
                <div className="md:col-span-2">
                  <Input label="Street Address" name="street_address" value={formData.street_address} onChange={e => setFormData({...formData, street_address: e.target.value})} placeholder="123 Ocean Drive" required />
                </div>
                <Input label="City" name="city" value={formData.city} onChange={e => setFormData({...formData, city: e.target.value})} placeholder="Miami" required />
                <Input
                  label="State" name="state" value={formData.state} onChange={e => setFormData({...formData, state: e.target.value})}
                  options={[
                    { value: 'NY', label: 'New York' },
                    { value: 'FL', label: 'Florida' },
                    { value: 'CA', label: 'California' },
                    { value: 'TX', label: 'Texas' },
                    { value: 'WA', label: 'Washington' }
                  ]}
                  required
                />
                <Input label="ZIP Code" name="zip_code" value={formData.zip_code} onChange={e => setFormData({...formData, zip_code: e.target.value})} placeholder="33139" required />
                <Input label="Country" name="country" value={formData.country} onChange={() => {}} options={[{value: 'USA', label: 'United States'}]} disabled />
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h2 className="text-3xl font-bold text-slate-800 mb-2">Property Details</h2>
              <p className="text-slate-500 mb-8">For houses or condos, provide bedroom info. For multi-unit buildings (apartment, duplex, triplex, quadplex), provide the number of units. Unit details can be managed individually after creation.</p>
              <label className="block text-sm font-medium text-slate-600 mb-4 ml-1">Property Type</label>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                {propertyTypes.map(type => (
                  <div
                    key={type.id}
                    onClick={() => setFormData({
                      ...formData,
                      property_type: type.id,
                      unit_count: defaultUnitCount[type.id] ?? formData.unit_count,
                    })}
                    className={`cursor-pointer p-6 rounded-2xl border-2 transition-all duration-300 flex flex-col items-center gap-3 ${formData.property_type === type.id ? 'bg-blue-50 border-blue-400 shadow-lg shadow-blue-500/10' : 'bg-slate-100 border-slate-200 hover:border-slate-300'}`}
                  >
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center transition-colors ${formData.property_type === type.id ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-600'}`}>
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={type.icon}></path></svg>
                    </div>
                    <span className={`text-sm font-bold ${formData.property_type === type.id ? 'text-blue-600' : 'text-slate-500'}`}>{type.name}</span>
                  </div>
                ))}
              </div>
              <div className="grid md:grid-cols-2 gap-8">
                {isMultiUnitType ? (
                  <Input
                    label="Number of units"
                    name="unit_count"
                    value={formData.unit_count}
                    onChange={e => setFormData({...formData, unit_count: e.target.value})}
                    placeholder={defaultUnitCount[formData.property_type] || 'e.g. 8'}
                    required
                  />
                ) : (
                  <Input label="Number of Bedrooms" name="bedrooms" value={formData.bedrooms} onChange={e => setFormData({...formData, bedrooms: e.target.value})} options={[
                    {value: '1', label: '1 Bedroom'}, {value: '2', label: '2 Bedrooms'}, {value: '3', label: '3 Bedrooms'}, {value: '4', label: '4 Bedrooms'}, {value: '5', label: '5+ Bedrooms'}
                  ]} />
                )}
                {!isMultiUnitType ? (
                  <div className="flex flex-col justify-center">
                    <label className="flex items-center gap-4 cursor-pointer p-4 rounded-xl bg-slate-100 border border-slate-200 hover:border-slate-300 transition-all">
                      <input
                        type="checkbox"
                        checked={formData.is_primary_residence}
                        onChange={e => setFormData({...formData, is_primary_residence: e.target.checked})}
                        className="w-6 h-6 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500"
                      />
                      <div>
                        <span className="block text-sm font-bold text-slate-800">Primary Residence?</span>
                        <span className="text-xs text-slate-500">Documented limits may vary for homestead properties.</span>
                      </div>
                    </label>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    <p className="text-sm font-medium text-slate-700">Do you live in one of the units?</p>
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!formData.primary_residence_unit}
                        onChange={e => {
                          if (!e.target.checked) setFormData({...formData, primary_residence_unit: ''});
                          else {
                            const uc = parseInt(formData.unit_count, 10);
                            setFormData({...formData, primary_residence_unit: (uc >= 1 ? '1' : '')});
                          }
                        }}
                        className="w-5 h-5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500"
                      />
                      <span className="text-sm text-slate-800">Yes, one unit is my primary residence</span>
                    </label>
                    {formData.primary_residence_unit && (() => {
                      const uc = Math.max(1, parseInt(formData.unit_count, 10) || 1);
                      return (
                        <div className="pl-8">
                          <label className="block text-xs font-medium text-slate-500 mb-1">Which unit?</label>
                          <select
                            value={formData.primary_residence_unit}
                            onChange={e => setFormData({...formData, primary_residence_unit: e.target.value})}
                            className="w-full max-w-xs px-3 py-2 border border-slate-300 rounded-lg text-sm"
                          >
                            {Array.from({ length: uc }, (_, i) => i + 1).map((n) => (
                              <option key={n} value={String(n)}>Unit {n}</option>
                            ))}
                          </select>
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h2 className="text-3xl font-bold text-slate-800 mb-2">Ownership Verification</h2>
              <p className="text-slate-500 mb-8">Upload proof of ownership.</p>
              <Input
                label="Type of Proof" name="proof_type" value={formData.proof_type} onChange={e => setFormData({...formData, proof_type: e.target.value})}
                options={[
                  { value: 'deed', label: 'Property Deed (Recommended)' },
                  { value: 'tax_bill', label: 'Property Tax Bill' },
                  { value: 'utility_bill', label: 'Recent Utility Bill' },
                  { value: 'mortgage_statement', label: 'Mortgage Statement' }
                ]}
              />
              <div
                className="mt-8 border-2 border-dashed border-slate-300 rounded-3xl p-12 text-center bg-white/55 backdrop-blur-lg group hover:border-blue-400/50 transition-all cursor-pointer"
                onClick={() => proofInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const file = e.dataTransfer?.files?.[0];
                  if (file && isAllowedProofFile(file)) setProofFile(file);
                  else if (file) notify('error', file.size > MAX_PROOF_SIZE ? 'File too large. Max 10MB.' : 'Please upload a PDF or image (JPEG, PNG).');
                }}
              >
                <input
                  ref={proofInputRef}
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file && isAllowedProofFile(file)) setProofFile(file);
                    else if (file) notify('error', file.size > MAX_PROOF_SIZE ? 'File too large. Max 10MB.' : 'Please upload a PDF or image (JPEG, PNG).');
                    e.target.value = '';
                  }}
                />
                <div className="w-16 h-16 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mx-auto mb-6 group-hover:scale-110 transition-transform">
                  <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                </div>
                <h4 className="text-xl font-bold text-slate-800 mb-2">Upload Proof of Ownership</h4>
                <p className="text-sm text-slate-500 mb-6">Drag and drop your file here, or click to browse. PDF or image (JPEG, PNG), max 10MB.</p>
                <Button type="button" variant="outline" className="px-8" onClick={(e) => { e.stopPropagation(); proofInputRef.current?.click(); }}>Select File</Button>
                {proofFile ? (
                  <div className="mt-6 flex items-center justify-center gap-2 text-green-600 font-bold text-sm bg-green-50 py-2 px-4 rounded-full w-fit mx-auto">
                    <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                    {proofFile.name}
                  </div>
                ) : (
                  <p className="mt-6 text-sm text-slate-500">No file selected</p>
                )}
              </div>
            </div>
          )}

          <div className="mt-12 pt-8 border-t border-slate-200 flex gap-4">
            {step > 1 ? (
              <Button type="button" variant="outline" onClick={() => setStep(step - 1)} className="px-10">Back</Button>
            ) : (
              <Button type="button" variant="outline" onClick={() => navigate('dashboard')} className="px-10">Cancel</Button>
            )}
            <Button
              type="submit"
              className="flex-1 py-4 text-xl"
              disabled={step === 3 && !proofFile}
            >
              {step === 3 ? 'Add property' : 'Continue to next step'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
};

export default AddProperty;
