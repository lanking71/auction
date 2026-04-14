import pickle
import os

def check_cookies():
    try:
        if not os.path.exists("auction_cookies.pkl"):
            print("쿠키 파일이 존재하지 않습니다.")
            return False
            
        with open("auction_cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
            
        required_cookies = ['auction', 'AGP', 'bcp']
        found_cookies = {cookie['name']: cookie['value'] for cookie in cookies if cookie['name'] in required_cookies}
        
        print("\n=== 쿠키 상태 ===")
        for name in required_cookies:
            if name in found_cookies:
                value = found_cookies[name]
                print(f"{name}: {'*' * min(len(value), 10)}... (길이: {len(value)})")
            else:
                print(f"{name}: 없음")
                
        return all(name in found_cookies for name in required_cookies)
        
    except Exception as e:
        print(f"쿠키 확인 중 오류 발생: {e}")
        return False

if __name__ == "__main__":
    check_cookies()