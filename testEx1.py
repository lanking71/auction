import pickle
from requests import Session

def check_session_cookies():
    try:
        # 저장된 쿠키 로드
        with open("auction_cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
        
        # 새로운 세션 생성
        session = Session()
        
        # 쿠키를 세션에 추가
        for cookie in cookies:
            session.cookies.set(
                name=cookie['name'],
                value=cookie['value'],
                domain=cookie.get('domain', '.auction.co.kr')
            )
        
        # 세션 쿠키 확인
        print("\n=== 세션 쿠키 상태 ===")
        for cookie in session.cookies:
            print(f"{cookie.name}: {cookie.value[:10]}... (길이: {len(cookie.value)})")
            
        return session
        
    except Exception as e:
        print(f"세션 쿠키 확인 중 오류: {e}")
        return None

if __name__ == "__main__":
    session = check_session_cookies()