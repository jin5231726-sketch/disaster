import math
import json
import urllib.request

import streamlit as st
import folium
from streamlit.components.v1 import html as st_html
from geopy.geocoders import Nominatim


# -----------------------------
# 1. 주소 -> 좌표 변환
# -----------------------------
@st.cache_data(show_spinner=False)
def get_coordinates(address):
    geolocator = Nominatim(user_agent="disaster_safety_webapp_v1")
    location = geolocator.geocode(address)
    if location:
        return location.latitude, location.longitude
    return None, None



# -----------------------------
# 3. 실제 주변 시설(병원/경찰서) OSM Overpass API 조회
#    geopandas 없이 순수 파이썬 하버사인 거리 계산으로 대체 (배포 단순화)
# -----------------------------
def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0  # 지구 반지름(m)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(a)))


# [교체] 카카오맵 -> Overpass -> Nominatim 순으로 시도했지만 전부 클라우드 서버 IP를 차단해서
# 계속 403/타임아웃이 발생했다. 그래서 프로그램이 대신 검색해주는 대신,
# 구글맵/카카오맵 "검색 링크"를 만들어 사용자가 직접 클릭해서 확인하도록 바꾼다.
# API 호출이 아예 없으므로 차단/타임아웃 걱정이 없고, 실시간 정확도도 가장 높다.
def build_map_search_links(lat, lon):
    google_hospital = f"https://www.google.com/maps/search/병원/@{lat},{lon},16z"
    google_police = f"https://www.google.com/maps/search/경찰서/@{lat},{lon},16z"
    google_shelter = f"https://www.google.com/maps/search/대피소/@{lat},{lon},16z"
    kakao_hospital = f"https://map.kakao.com/?q=병원&urlX={lon}&urlY={lat}"
    kakao_police = f"https://map.kakao.com/?q=경찰서&urlX={lon}&urlY={lat}"
    kakao_shelter = f"https://map.kakao.com/?q=대피소&urlX={lon}&urlY={lat}"
    return {
        "hospital": {"google": google_hospital, "kakao": kakao_hospital},
        "police": {"google": google_police, "kakao": kakao_police},
        "shelter": {"google": google_shelter, "kakao": kakao_shelter},
    }

def predict_earthquake_scenario(score):
    if score >= 85:
        grade = "A등급 (상대적 안전 우수)"
        before = "입력하신 조건상 구조·연식·경사 요인의 감점이 적은 편입니다."
        after = ("다른 등급 대비 붕괴 위험이 낮게 추정되나, 이는 몇 가지 변수로 계산한 참고용 점수일 뿐 "
                 "전문 구조기술사의 내진성능평가를 대체하지 않습니다. 실제 강진 발생 시에도 반드시 대피 매뉴얼에 따라 행동해야 합니다.")
    elif score >= 60:
        grade = "B등급 (양호/주의)"
        before = "노후화가 다소 진행되었거나 과거 내진 기준이 적용되어 보완이 필요할 수 있는 상태입니다."
        after = ("강한 흔들림 발생 시 천장 마감재, 조명 기구의 낙하 위험이 있습니다. 외벽 균열이 발생할 수 있으므로, "
                 "지진 직후 책상 밑으로 신속히 대피한 뒤 계단을 통해 공터로 즉시 탈출해야 합니다.")
    else:
        grade = "X등급 (붕괴 위험 고조)"
        before = "지진에 취약한 구조(조적조 등)이거나 내진 설계 기준 적용 이전 건물로 추정됩니다."
        after = ("구조부(기둥, 보)에 손상이 생겨 붕괴로 이어질 위험이 상대적으로 높게 추정됩니다. 탈출로가 차단될 수 있으므로, "
                 "대피 경보 즉시 머리를 보호하며 건물 밖으로 대피하는 것을 우선 고려해야 합니다.")
    return grade, before, after


# -----------------------------
# 5. 종합 안전성 점수 계산 (2017년 내진기준 강화 반영)
# -----------------------------
def evaluate_comprehensive_safety(structure, year, floors, elevation, slope, river_dist):
    eq_score = 100
    if structure in ["벽돌조", "조적조", "블록조"]:
        eq_score -= 40
    elif structure in ["목조", "황토구조"]:
        eq_score -= 25

    if year < 1988:
        eq_score -= 55   # 내진설계 의무화 이전 - 내진 개념 자체가 없던 시기
    elif year < 2000:
        eq_score -= 35   # 초기 내진기준(약한 기준) 적용 구간
    elif year < 2017:
        eq_score -= 15   # 2017 포항지진 이전, 현행 기준보다 약한 기준 적용 구간

    if slope >= 25:
        eq_score -= 20
    elif slope >= 10:
        eq_score -= 10
    if floors >= 16:
        eq_score -= 25
    elif floors >= 6:
        eq_score -= 15

    flood_score = 100
    if elevation < 15:
        flood_score -= 40
    elif elevation < 30:
        flood_score -= 20
    if river_dist < 100:
        flood_score -= 30
    elif river_dist < 500:
        flood_score -= 15
    if floors == 1:
        flood_score -= 30
    elif floors <= 3:
        flood_score -= 15

    typhoon_score = 100
    if floors >= 16:
        typhoon_score -= 40
    elif floors >= 4:
        typhoon_score -= 20
    if slope >= 15:
        typhoon_score -= 30
    if (2026 - year) >= 15:
        typhoon_score -= 30

    eq_score, flood_score, typhoon_score = max(0, eq_score), max(0, flood_score), max(0, typhoon_score)
    return {
        "지진점수": eq_score, "홍수점수": flood_score, "태풍점수": typhoon_score,
        "종합점수": min(eq_score, flood_score, typhoon_score)
    }


# =========================================================
# 🚀 Streamlit 화면 구성
# =========================================================
st.set_page_config(page_title="재난 안전성 평가 시스템", page_icon="🚨", layout="centered")
st.title("🚨 건물 재난 안전성 평가 및 구호 기관 안내")
st.warning(
    "⚠️ **이 앱은 간이 추정 모델입니다.** 몇 가지 변수(구조/연식/층수/경사 등)를 바탕으로 만든 "
    "**참고용·교육용 점수**이며, 정밀한 공학적 계산이나 정부 고시 기준을 따른 것이 아닙니다. "
    "실제 건물의 내진 안전성은 지자체의 내진성능평가 제도나 전문 구조기술사의 진단을 통해 확인하세요. "
    "이 점수만으로 안전/위험 여부를 최종 판단하지 마세요."
)

address = st.text_input("1. 분석할 건물 주소를 입력하세요", placeholder="예: 서울특별시 종로구 세종대로 1")

if address:
    with st.spinner("주소 확인 및 지형 정보 수집 중..."):
        lat, lon = get_coordinates(address)

    if lat is None:
        st.error("❌ 주소를 찾을 수 없습니다. 다른 형식으로 다시 입력해보세요.")
    else:
        st.success(f"주소 확인 완료! (위도 {lat:.4f}, 경도 {lon:.4f})")
        elevation, slope, river_dist = 25.0, 8.5, 350.0  # 임시값: 실서비스 배포 시 실제 GIS API로 교체 필요
        st.info(f"지형 조건은 현재 임시값으로 계산됩니다 (해발고도 {elevation}m, 경사도 {slope}°, 하천거리 {river_dist}m)")

        st.subheader("2. 건축물 정보 입력")
        col1, col2, col3 = st.columns(3)
        with col1:
            structure = st.selectbox("건물 구조", ["철근콘크리트", "벽돌조", "조적조", "블록조", "목조", "황토구조"])
        with col2:
            year = st.number_input("준공 연도", min_value=1900, max_value=2026, value=2010, step=1)
        with col3:
            floors = st.number_input("층수", min_value=1, max_value=100, value=4, step=1)

        if st.button("평가하기", type="primary"):
            scores = evaluate_comprehensive_safety(structure, int(year), int(floors), elevation, slope, river_dist)
            grade, before, after = predict_earthquake_scenario(scores["종합점수"])

            st.subheader("📊 평가 결과")
            st.caption("⚠️ 간이 추정 모델 결과입니다. 정밀 진단이 아니며 실제 안전 판단의 근거로 쓰지 마세요.")
            c1, c2, c3 = st.columns(3)
            c1.metric("지진 점수", f"{scores['지진점수']}점")
            c2.metric("홍수 점수", f"{scores['홍수점수']}점")
            c3.metric("태풍 점수", f"{scores['태풍점수']}점")

            st.markdown(f"### ⭐ 종합 등급: {grade} (종합 점수 {scores['종합점수']}점)")
            st.write(f"**현재 상태 추정**: {before}")
            st.write(f"**지진 시 상황 예측**: {after}")

            st.subheader("🏃 주변 구호 기관 찾기")
            st.caption("아래 버튼을 누르면 지도 앱에서 실시간으로 가장 정확한 위치를 바로 확인할 수 있습니다.")
            links = build_map_search_links(lat, lon)

            col_h, col_p, col_s = st.columns(3)
            with col_h:
                st.markdown(f"🏥 **응급 의료원**\n\n[구글맵에서 찾기]({links['hospital']['google']})\n\n[카카오맵에서 찾기]({links['hospital']['kakao']})")
            with col_p:
                st.markdown(f"🚔 **치안/구조처**\n\n[구글맵에서 찾기]({links['police']['google']})\n\n[카카오맵에서 찾기]({links['police']['kakao']})")
            with col_s:
                st.markdown(f"🚨 **지정 대피소**\n\n[구글맵에서 찾기]({links['shelter']['google']})\n\n[카카오맵에서 찾기]({links['shelter']['kakao']})")

            b_color = "green" if scores["종합점수"] >= 85 else ("orange" if scores["종합점수"] >= 60 else "red")
            m = folium.Map(location=[lat, lon], zoom_start=15)
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(f"<b>대상 건물 안전 추정 점수: {scores['종합점수']}점</b><br>{grade}", max_width=250),
                icon=folium.Icon(color=b_color, icon="home"),
            ).add_to(m)

            st_html(m._repr_html_(), height=500)
