Name:           scls-release
Version:        2026
Release:        1%{?dist}
Summary:        SCLS repository configuration and GPG key

License:        BSD-3-Clause-LBNL
URL:            https://belfem.lbl.gov/scls

Source0:        scls.repo
Source1:        RPM-GPG-KEY-SCLS

BuildArch:      noarch

%description
This package provides the repository configuration and GPG key
for the Scientific Core Library Stack (SCLS).

%install
install -Dpm 644 %{SOURCE0} %{buildroot}/etc/yum.repos.d/scls.repo
install -Dpm 644 %{SOURCE1} %{buildroot}/etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS

%files
/etc/yum.repos.d/scls.repo
/etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS
